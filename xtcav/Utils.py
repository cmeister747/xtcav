#(c) Coded by Alvaro Sanchez-Gonzalez 2014
#Functions related with the XTCAV pulse retrieval
import numpy as np
import scipy.interpolate
import time
import warnings
import cv2
import scipy.io
import math
import cv2
import Constants
from sklearn.cluster import AgglomerativeClustering, DBSCAN
from sklearn import metrics
import collections
import SplittingUtils as su
import scipy.ndimage as im 
import collections


def getImageStatistics(image, ROI):
    """
    Obtain the statistics (profiles, center of mass, etc) of an xtcav image. 
    Arguments:
        image: 3d numpy array where the first index always has one dimension (it will become the bunch index), the second index correspond to y, and the third index corresponds to x
        ROI: region of interest of the image, contain x and y axis
    Output:
        imageStats: list with the image statistics for each bunch in the image
    """

    num_bunches = image.shape[0]
    #For the image for each bunch we retrieve the statistics and add them to the list    
    imageStats=[]    
    for i in range(num_bunches):
        cur_image = image[i, :, :]
        imFrac = np.sum(cur_image)    #Total area of the image: Since the original image is normalized, this should be on for on bunch retrievals, and less than one for multiple bunches
        
        xProfile = np.sum(cur_image, axis=0)  #Profile projected onto the x axis
        yProfile = np.sum(cur_image, axis=1)  #Profile projected onto the y axis
        
        xCOM = np.dot(xProfile,np.transpose(ROI.x))/imFrac        #X position of the center of mass
        xRMS = np.sqrt(np.dot((ROI.x-xCOM)**2,xProfile)/imFrac) #Standard deviation of the values in x
        ind = np.where(xProfile >= np.amax(xProfile)/2)[0]   
        xFWHM = np.abs(ind[-1]-ind[0]+1)                     #FWHM of the X profile

        yCOM = np.dot(yProfile,ROI.y)/imFrac                      #Y position of the center of mass
        yRMS = np.sqrt(np.dot((ROI.y-yCOM)**2,yProfile)/imFrac) #Standard deviation of the values in y
        ind = np.where(yProfile >= np.amax(yProfile)/2)
        yFWHM = np.abs(ind[-1]-ind[0])                        #FWHM of the Y profile
        
        yCOMslice = divideNoWarn(np.dot(np.transpose(cur_image),ROI.y), xProfile, yCOM)   #Y position of the center of mass for each slice in x
        distances = np.outer(np.ones(yCOMslice.shape[0]),ROI.y)-np.outer(yCOMslice,np.ones(cur_image.shape[0]))    #For each point of the image, the distance to the y center of mass of the corresponding slice
        yRMSslice =  divideNoWarn(np.sum(np.transpose(cur_image)*((distances)**2), axis=1), xProfile, 0)         #Width of the distribution of the points for each slice around the y center of masses                  
        yRMSslice = np.sqrt(yRMSslice)
        
        if imFrac == 0:   #What to do if the image was effectively full of zeros
            xCOM = float(ROI.x[-1]+ROI.x[0])/2
            yCOM = float(ROI.y[-1]+ROI.y[0])/2
            yCOMslice[np.isnan(yCOMslice)] = yCOM

            imageStats.append(ImageStatistics(imFrac, xProfile, yProfile, xCOM, yCOM, yCOMslice, yRMSslice))
            continue

        imageStats.append(ImageStatistics(imFrac, xProfile, yProfile, xCOM,
            yCOM, xRMS, yRMS, xFWHM, yFWHM, yCOMslice, yRMSslice))
        
    return imageStats
    

def getCenterOfMass(image,x,y):
    """
    Gets the center of mass of an image 
    Arguments:
      image: 2d numpy array where the firs index correspond to y, and the second index corresponds to x
      x,y: vectors of the image
    Output:
      x0,y0 coordinates of the center of mass 
    """
    profilex = np.sum(image, axis=0)     
    x0 = np.dot(profilex, np.transpose(x))/np.sum(profilex)
    profiley = np.sum(image, axis=1);     
    y0 = np.dot(profiley, y)/np.sum(profiley)
    
    return x0,y0
    
    
def subtractBackground(image, ROI, dark_background):
    """
    Obtain all the statistics (profiles, center of mass, etc) of an image
    Arguments:
      image: 2d numpy array where the first index correspond to y, and the second index corresponds to x
      ROI: region of interest of the input image
      darkbg: struct with the dark background image and its ROI
    Output
      image: image after subtracting the background
      ROI: region of interest of the ouput image
    """

    #This only contemplates the case when the ROI of the darkbackground is larger than the ROI of the image. Other cases should be contemplated in the future
    if dark_background:
        image_db = dark_background.image
        ROI_db = dark_background.ROI
        minX = ROI.x0 - ROI_db.x0
        maxX = (ROI.x0+ROI.xN-1)-ROI_db.x0
        minY = ROI.y0-ROI_db.y0
        maxY = (ROI.y0+ROI.yN-1)-ROI_db.y0

        try:    
            image = image-image_db[minY:(maxY+1),minX:(maxX+1)]
        except ValueError:
            warnings.warn_explicit('Dark background ROI not large enough for image. Image will not be background subtracted',UserWarning,'XTCAV',0)
       
    return image

    
def denoiseImage(image, snrfilter):
    """
    Get rid of some of the noise in the image (profiles, center of mass, etc) of an image
    Note: if you find that all of your images are registering as 'Empty', try decreasing the snrfilter parameter
    in both your lasing off reference and lasing on analysis.
    Arguments:
      image: 2d numpy array where the first index correspond to y, and the second index corresponds to x
      medianfilter: number of neighbours for the median filter
      snrfilter: factor to multiply the standard deviation of the noise to use as a threshold
    Output
      image: filtered image
      contains_data: true if there is something in the image
    """
    #Applying the gaussian filter
    filtered = cv2.GaussianBlur(image, (5, 5), 0)

    if np.sum(filtered) <= 0:
        warnings.warn_explicit('Image Completely Empty After Backgroud Subtraction', UserWarning,'XTCAV',0)
        return None, None
    
    #Obtaining the mean and the standard deviation of the noise by using pixels only on the border
    mean = np.mean(filtered[0:Constants.SNR_BORDER,0:Constants.SNR_BORDER])
    std = np.std(filtered[0:Constants.SNR_BORDER,0:Constants.SNR_BORDER])

    #Create a mask for the true image that allows us to zero out all noise portions of image
    mask = cv2.threshold(filtered.astype(np.float32), mean + snrfilter*std, 1, cv2.THRESH_BINARY)[1]
    if np.sum(mask) == 0:
        warnings.warn_explicit('Image Completely Empty After Denoising',UserWarning,'XTCAV',0)
        return None, None
     #We make sure it is not just noise by checking that at least .1% of pixels are not empty
    if float(np.count_nonzero(mask))/np.size(mask) < Constants.VALID_PIXEL_PERCENTAGE: 
        warnings.warn_explicit('< %.4f %% of pixels are non-zero after denoising. Image will not be used' % Constants.VALID_PIXEL_PERCENTAGE*10,UserWarning,'XTCAV',0)
        return None, None

    return mask, mean


def maskImage(img, mean, masks, roi):
    """
    Crop to roi; zero out noise and negative values; normalize image so that all values sum to 1
    Arguments:
      image: 2d numpy array where the first index correspond to y, and the second index corresponds to x
      mean: mean of noise region in image
      masks: filter with 1 in areas where we keep pixel value and 0 where we "zero-out" pixel value
      roi: region of interest
    Output
      image: masked images (each bunch is on its own)
    """
    
    croppedimg = img[roi.y0:roi.y0+roi.yN-1,roi.x0:roi.x0+roi.xN-1]
    croppedimg -= mean
    output = np.zeros(masks.shape)
    for i in range(masks.shape[0]):
        output[i] = croppedimg
        output[i][np.logical_or(masks[i] == 0, croppedimg < 0)] = 0
    output = output/np.sum(output)
    return output


def findROI(masks, ROI, expandfactor=1):
    """
    Find the subroi of the image
    Arguments:
      image: 2d numpy array where the first index correspond to y, and the second index corresponds to x
      ROI: region of interest of the input image
      threshold: fraction of one that will set where the signal has dropped enough from the maximum to consider it to be the width the of trace
      expandfactor: factor that will increase the calculated width from the maximum to where the signal drops to threshold
    Output
      cropped: 2d numpy array with the cropped image where the first index correspond to y, and the second index corresponds to x
      outROI: region of interest of the output image
    """

    #For the cropping on each direction we use the profile on each direction
    total = masks.sum(axis=0)
    rows = np.any(total, axis=1)
    cols = np.any(total, axis=0)
    ymin, ymax = np.where(rows)[0][[0, -1]]
    xmin, xmax = np.where(cols)[0][[0, -1]]

    widthy = (ymax - ymin +1)*expandfactor
    centery = (ymax + ymin +1)/2
    widthx = (xmax - xmin +1)*expandfactor
    centerx = (xmax + xmin +1)/2

    ind1Y = max(0, np.round(centery - widthy/2).astype(np.int))
    ind2Y = min(np.round(centery + widthy/2).astype(np.int), rows.size)
    ind1X = max(0, np.round(centerx - widthx/2).astype(np.int))
    ind2X = min(np.round(centerx + widthx/2).astype(np.int), cols.size)
                
    #Output ROI in terms of the input ROI            
    outROI = ROIMetrics(ind2X-ind1X+1, 
        ROI.x0+ind1X, 
        ind2Y-ind1Y+1, 
        ROI.y0+ind1Y, 
        x=ROI.x0+np.arange(ind1X, ind2X), 
        y=ROI.y0+np.arange(ind1Y, ind2Y))
    
    return masks[:,ind1Y:ind2Y,ind1X:ind2X], outROI


def calculatePhyscialUnits(ROI, center, shot_to_shot, global_calibration):
    valid=1
    yMeVPerPix = global_calibration.umperpix*global_calibration.dumpe/global_calibration.dumpdisp*1e-3          #Spacing of the y axis in MeV
    
    xfsPerPix = -global_calibration.umperpix*global_calibration.rfampcalib/(0.3*global_calibration.strstrength*shot_to_shot.xtcavrfamp)     #Spacing of the x axis in fs (this can be negative)
    
    cosphasediff=math.cos((global_calibration.rfphasecalib-shot_to_shot.xtcavrfphase)*math.pi/180)

    #If the cosine of phase was too close to 0, we return warning and error
    if np.abs(cosphasediff) < 0.5:
        warnings.warn_explicit('The phase of the bunch with the RF field is far from 0 or 180 degrees',UserWarning,'XTCAV',0)
        valid=0

    signflip = np.sign(cosphasediff); #It may need to be flipped depending on the phase

    xfsPerPix = signflip*xfsPerPix;    
    
    xfs=xfsPerPix*(ROI.x-center[0])                  #x axis in fs around the center of mass
    yMeV=yMeVPerPix*(ROI.y-center[1])                #y axis in MeV around the center of mass

    return PhysicalUnits(xfs, yMeV, xfsPerPix, yMeVPerPix, valid)


def processImage(img, parameters, dark_background, global_calibration, 
        saturation_value, roi, shot_to_shot):
        """
        Run decomposition algorithms on xtcav image. This method is called automatically and should not be called by the user unless he has a knowledge of the operation done by this class internally

        Returns:
            ImageProfile ( image_stats,  roi, shot_to_shot, physical_units)
            processed image
        """
        # skip if empty image or saturated
        if img is None: 
            return None, None

        if np.max(img) >= saturation_value:
            warnings.warn_explicit('Saturated Image',UserWarning,'XTCAV',0)
            return None, None

        #Subtract the dark background, taking into account properly possible different ROIs, if it is available
        img_db = subtractBackground(img, roi, dark_background) 
        croppedimg =  img_db[roi.y0:roi.y0+roi.yN-1,roi.x0:roi.x0+roi.xN-1]

        mask, mean = denoiseImage(croppedimg, parameters.snr_filter)                    #Remove noise from the image and normalize it
        if mask is None:   #If there is nothing in the image we skip the event  
            return None, None
        
        masks = su.splitImage(mask, parameters.num_bunches, parameters.island_split_method, 
            parameters.island_split_par1, parameters.island_split_par2)#new

        if masks is None:  #If there is nothing in the image we skip the event  
            return None, None

        num_bunches_found = masks.shape[0]
        if parameters.num_bunches != num_bunches_found:
            warnings.warn_explicit('Incorrect number of bunches detected in image.', UserWarning, 'XTCAV',0)
            return None, None

        masks, roi = findROI(masks, roi, parameters.roi_expand)                  #Crop the image, the ROI struct is changed. It also add an extra dimension to the image so the array can store multiple images corresponding to different bunches
        processed_image = maskImage(img_db, mean, masks, roi)
        image_stats = getImageStatistics(processed_image, roi)          #Obtain the different properties and profiles from the trace               
        physical_units = calculatePhyscialUnits(roi,(image_stats[0].xCOM,image_stats[0].yCOM), shot_to_shot, global_calibration)   
        if not physical_units.valid:
            return None, None

        #If the step in time is negative, we mirror the x axis to make it ascending and consequently mirror the profiles
        if physical_units.xfsPerPix < 0:
            physical_units = physical_units._replace(xfs = physical_units.xfs[::-1])
            for j in range(num_bunches_found):
                image_stats[j] = image_stats[j]._replace(xProfile = image_stats[j].xProfile[::-1], 
                    yCOMslice = image_stats[j].yCOMslice[::-1], yRMSslice = image_stats[j].yRMSslice[::-1])

        return ImageProfile(image_stats, roi, shot_to_shot, physical_units), processed_image


def processLasingSingleShot(image_profile, nolasing_averaged_profiles):
    """
    Process a single shot profiles, using the no lasing references to retrieve the x-ray pulse(s)
    Arguments:
      image_profile: profile for xtcav image
      nolasing_averaged_profiles: no lasing reference profiles
    Output
      pulsecharacterization: retrieved pulse
    """

    image_stats = image_profile.image_stats
    physical_units = image_profile.physical_units
    shot_to_shot = image_profile.shot_to_shot

    num_bunches = len(image_stats)              #Number of bunches
    
    if (num_bunches != nolasing_averaged_profiles.num_bunches):
        warnings.warn_explicit('Different number of bunches in the reference',UserWarning,'XTCAV',0)
    
    t = nolasing_averaged_profiles.t   #Master time obtained from the no lasing references
    dt = (t[-1]-t[0])/(t.size-1)
    
             #Electron charge in coulombs
    Nelectrons = shot_to_shot.dumpecharge/Constants.E_CHARGE   #Total number of electrons in the bunch    
    
    #Create the the arrays for the outputs, first index is always bunch number
    bunchdelay=np.zeros(num_bunches, dtype=np.float64);                       #Delay from each bunch with respect to the first one in fs
    bunchdelaychange=np.zeros(num_bunches, dtype=np.float64);                 #Difference between the delay from each bunch with respect to the first one in fs and the same form the non lasing reference
    bunchenergydiff=np.zeros(num_bunches, dtype=np.float64);                  #Distance in energy for each bunch with respect to the first one in MeV
    bunchenergydiffchange=np.zeros(num_bunches, dtype=np.float64);            #Comparison of that distance with respect to the no lasing
    eBunchCOM=np.zeros(num_bunches, dtype=np.float64);                   #Energy of the XRays generated from each bunch for the center of mass approach in J
    eBunchRMS=np.zeros(num_bunches, dtype=np.float64);                   #Energy of the XRays generated from each bunch for the dispersion of mass approach in J
    powerAgreement=np.zeros(num_bunches, dtype=np.float64);              #Agreement factor between the two methods
    lasingECurrent=np.zeros((num_bunches,t.size), dtype=np.float64);     #Electron current for the lasing trace (In #electrons/s)
    nolasingECurrent=np.zeros((num_bunches,t.size), dtype=np.float64);   #Electron current for the no lasing trace (In #electrons/s)
    lasingECOM=np.zeros((num_bunches,t.size), dtype=np.float64);         #Lasing energy center of masses for each time in MeV
    nolasingECOM=np.zeros((num_bunches,t.size), dtype=np.float64);       #No lasing energy center of masses for each time in MeV
    lasingERMS=np.zeros((num_bunches,t.size), dtype=np.float64);         #Lasing energy dispersion for each time in MeV
    nolasingERMS=np.zeros((num_bunches,t.size), dtype=np.float64);       #No lasing energy dispersion for each time in MeV
    powerECOM=np.zeros((num_bunches,t.size), dtype=np.float64);      #Retrieved power in GW based on ECOM
    powerERMS=np.zeros((num_bunches,t.size), dtype=np.float64);      #Retrieved power in GW based on ERMS

    powerrawECOM=np.zeros((num_bunches,t.size), dtype=np.float64);              #Retrieved power in GW based on ECOM without gas detector normalization
    powerrawERMS=np.zeros((num_bunches,t.size), dtype=np.float64);              #Retrieved power in arbitrary units based on ERMS without gas detector normalization
    groupnum=np.zeros(num_bunches, dtype=np.int32);                  #group number of lasing off shot
             
    
    #We treat each bunch separately
    for j in range(num_bunches):
        distT=(image_stats[j].xCOM-image_stats[0].xCOM)*physical_units.xfsPerPix  #Distance in time converted form pixels to fs
        distE=(image_stats[j].yCOM-image_stats[0].yCOM)*physical_units.yMeVPerPix #Distance in time converted form pixels to MeV
        
        bunchdelay[j]=distT  #The delay for each bunch is the distance in time
        bunchenergydiff[j]=distE #Same for energy
        
        dt_old=physical_units.xfs[1]-physical_units.xfs[0] # dt before interpolation 
        
        eCurrent=image_stats[j].xProfile/(dt_old*Constants.FS_TO_S)*Nelectrons                        #Electron current in number of electrons per second, the original xProfile already was normalized to have a total sum of one for the all the bunches together
        
        eCOMslice=(image_stats[j].yCOMslice-image_stats[j].yCOM)*physical_units.yMeVPerPix       #Center of mass in energy for each t converted to the right units        
        eRMSslice=image_stats[j].yRMSslice*physical_units.yMeVPerPix                               #Energy dispersion for each t converted to the right units

        interp=scipy.interpolate.interp1d(physical_units.xfs-distT,eCurrent,kind='linear',fill_value=0,bounds_error=False,assume_sorted=True)  #Interpolation to master time
        eCurrent=interp(t)    
                                                   
        interp=scipy.interpolate.interp1d(physical_units.xfs-distT,eCOMslice,kind='linear',fill_value=0,bounds_error=False,assume_sorted=True)  #Interpolation to master time
        eCOMslice=interp(t)
            
        interp=scipy.interpolate.interp1d(physical_units.xfs-distT,eRMSslice,kind='linear',fill_value=0,bounds_error=False,assume_sorted=True)  #Interpolation to master time
        eRMSslice=interp(t)        
        
        #Find best no lasing match
        num_groups=nolasing_averaged_profiles.eCurrent[j].shape[0]
        corr = np.apply_along_axis(lambda x: np.corrcoef(eCurrent, x)[0,1]**2, 1, nolasing_averaged_profiles.eCurrent[j])
        
        #The index of the most similar is that with a highest correlation, i.e. the last in the array after sorting it
        groupnum[j]=np.argmax(corr)
        #groupnum[j] = np.random.randint(0, num_groups-1) if num_groups > 1 else 0
        
        #The change in the delay and in energy with respect to the same bunch for the no lasing reference
        bunchdelaychange[j]=distT-nolasing_averaged_profiles.distT[j][groupnum[j]]
        bunchenergydiffchange[j]=distE-nolasing_averaged_profiles.distE[j][groupnum[j]]
                                       
        #We do proper assignations
        lasingECurrent[j,:]=eCurrent
        nolasingECurrent[j,:]=nolasing_averaged_profiles.eCurrent[j][groupnum[j],:]

        #We threshold the ECOM and ERMS based on electron current
        threslevel=0.1
        threslasing=np.amax(lasingECurrent[j,:])*threslevel
        thresnolasing=np.amax(nolasingECurrent[j,:])*threslevel      
        indiceslasing=np.where(lasingECurrent[j,:]>threslasing)
        indicesnolasing=np.where(nolasingECurrent[j,:]>thresnolasing)      
        ind1=np.amax([indiceslasing[0][0],indicesnolasing[0][0]])
        ind2=np.amin([indiceslasing[0][-1],indicesnolasing[0][-1]])        
        if ind1>ind2:
            ind1=ind2
        
        #And do the rest of the assignations taking into account the thresholding
        lasingECOM[j,ind1:ind2]=eCOMslice[ind1:ind2]
        nolasingECOM[j,ind1:ind2]=nolasing_averaged_profiles.eCOMslice[j][groupnum[j],ind1:ind2]
        lasingERMS[j,ind1:ind2]=eRMSslice[ind1:ind2]
        nolasingERMS[j,ind1:ind2]=nolasing_averaged_profiles.eRMSslice[j][groupnum[j],ind1:ind2]
        
        #First calculation of the power based on center of masses and dispersion for each bunch
        powerECOM[j,:]=((nolasingECOM[j]-lasingECOM[j])*Constants.E_CHARGE*1e6)*eCurrent    #In J/s
        powerERMS[j,:]=(lasingERMS[j]**2-nolasingERMS[j]**2)*(eCurrent**(2.0/3.0)) #
        
    powerrawECOM=powerECOM*1e-9 
    powerrawERMS=powerERMS.copy()
    #Calculate the normalization constants to have a total energy compatible with the energy detected in the gas detector
    eoffsetfactor=(shot_to_shot.xrayenergy-(np.sum(powerECOM)*dt*Constants.FS_TO_S))/Nelectrons   #In J                           
    escalefactor=np.sum(powerERMS)*dt*Constants.FS_TO_S                 #in J
    
    
    #Apply the corrections to each bunch and calculate the final energy distribution and power agreement
    for j in range(num_bunches):                 
        powerECOM[j,:]=((nolasingECOM[j,:]-lasingECOM[j,:])*Constants.E_CHARGE*1e6+eoffsetfactor)*lasingECurrent[j,:]*1e-9   #In GJ/s (GW)
        powerERMS[j,:]=shot_to_shot.xrayenergy*powerERMS[j,:]/escalefactor*1e-9   #In GJ/s (GW)        
        powerAgreement[j]=1-np.sum((powerECOM[j,:]-powerERMS[j,:])**2)/(np.sum((powerECOM[j,:]-np.mean(powerECOM[j,:]))**2)+np.sum((powerERMS[j,:]-np.mean(powerERMS[j,:]))**2))
        eBunchCOM[j]=np.sum(powerECOM[j,:])*dt*Constants.FS_TO_S*1e9
        eBunchRMS[j]=np.sum(powerERMS[j,:])*dt*Constants.FS_TO_S*1e9
                    
    return PulseCharacterization(t, powerrawECOM, powerrawERMS, powerECOM, 
        powerERMS, powerAgreement, bunchdelay, bunchdelaychange, shot_to_shot.xrayenergy, 
        eBunchCOM, eBunchRMS, bunchenergydiff, bunchenergydiffchange, lasingECurrent,
        nolasingECurrent, lasingECOM, nolasingECOM, lasingERMS, nolasingERMS, num_bunches, 
        groupnum)
    
def averageXTCAVProfilesGroups(list_image_profiles, num_groups, method='hierarchical'):
    """
    Cluster together profiles of xtcav images
    Arguments:
      list_image_profiles: list of the image profiles for all the XTCAV non lasing profiles to average
      shots_per_group
    Output
      averagedProfiles: list with the averaged reference of the reference for each group 
    """
   
    list_image_stats = [profile.image_stats for profile in list_image_profiles]
    list_physical_units = [profile.physical_units for profile in list_image_profiles]
    list_shot_to_shot = [profile.shot_to_shot for profile in list_image_profiles]

    num_profiles = len(list_image_profiles)           #Total number of profiles
    num_bunches = len(list_image_stats[0])       #Number of bunches

    B = 20
    # Obtain physical units and calculate time vector   
    #We find adequate values for the master time
    maxt = np.amax([np.amax(l.xfs) for l in list_physical_units])
    mint = np.amin([np.amin(l.xfs) for l in list_physical_units])
    mindt = np.amin([np.abs(l.xfsPerPix) for l in list_physical_units])

    #Obtain the number of electrons in each shot
    num_electrons = np.array([x.dumpecharge/Constants.E_CHARGE for x in list_shot_to_shot])

    #To be safe with the master time, we set it to have a step half the minumum step
    dt=mindt/2

    #And create the master time vector in fs
    t=np.arange(mint,maxt+dt,dt)

    averageECurrent = []      #Electron current in (#electrons/s)
    averageECOMslice = []   #Energy center of masses for each time in MeV
    averageERMSslice = []      #Energy dispersion for each time in MeV
    averageDistT = []                #Distance in time of the center of masses with respect to the center of the first bunch in fs
    averageDistE = []                #Distance in energy of the center of masses with respect to the center of the first bunch in MeV
    averageTRMS = []                  #Total dispersion in time in fs
    averageERMS = []                 #Total dispersion in energy in MeV
    eventTime = []
    eventFid = []

    #We treat each bunch separately, even group them separately
    for j in range(num_bunches):
        #Decide which profiles are going to be in which groups and average them together
        #Calculate interpolated profiles of electron current in time for comparison
        profilesT = np.zeros((num_profiles,len(t)), dtype=np.float64)  
        for i in range(num_profiles): 
            distT=(list_image_stats[i][j].xCOM-list_image_stats[i][0].xCOM)*list_physical_units[i].xfsPerPix
            profilesT[i,:]=scipy.interpolate.interp1d(list_physical_units[i].xfs-distT,list_image_stats[i][j].xProfile, kind='linear',fill_value=0,bounds_error=False,assume_sorted=True)(t)
        
        num_clusters = findOptGroups(profilesT, B, 10) if not num_groups else num_groups  

        if num_profiles == 1:
            groups = np.array([0]) 
        #for debugging. can remove without repercussions
        elif num_clusters >= num_profiles:
            groups = np.array(list(range(num_profiles)))
        else: 
            if method.lower() == 'hierarchical':
                groups = hierarchicalClustering(profilesT, num_clusters)
            elif method.lower() == 'old':
                groups = oldGroupingMethod(profilesT, num_clusters)
            elif method.lower() == 'svd':
                num_features=10
                u, s, v = np.linalg.svd(profilesT.T)
                W = u[:, 0:num_features - 1]
                newX = np.matmul(profilesT, W)
                groups = hierarchicalClustering(newX, num_clusters)
            elif method.lower() == 'cosine':
                groups = hierarchicalClustering(profilesT, num_clusters, distance='cosine')
            elif method.lower() == 'kmeans':
                model = DBSCAN()
                model.fit(profilesT)
                groups = model.labels_
            elif method.lower() == 'l1':
                groups = hierarchicalClustering(profilesT, num_clusters, distance='l1')
            else:
                print "Clustering method ", method, " not supported. Using hierarchical"
                groups = hierarchicalClustering(profilesT, num_clusters)
        
        num_clusters = max(groups) + 1
        print "Averaging lasing off profiles into ", num_clusters, " groups."   


    #Create the the arrays for the outputs, first index is always bunch number, and second index is group number

        averageECurrent.append(np.zeros((num_clusters, len(t)), dtype=np.float64))
        averageECOMslice.append(np.zeros((num_clusters, len(t)), dtype=np.float64))      #Energy center of masses for each time in MeV
        averageERMSslice.append(np.zeros((num_clusters, len(t)), dtype=np.float64))      #Energy dispersion for each time in MeV
        averageDistT.append(np.zeros(num_clusters, dtype=np.float64))                 #Distance in time of the center of masses with respect to the center of the first bunch in fs
        averageDistE.append(np.zeros(num_clusters, dtype=np.float64))                 #Distance in energy of the center of masses with respect to the center of the first bunch in MeV
        averageTRMS.append(np.zeros(num_clusters, dtype=np.float64))                  #Total dispersion in time in fs
        averageERMS.append(np.zeros(num_clusters, dtype=np.float64))                 #Total dispersion in energy in MeV
        eventTime.append(np.zeros(num_clusters, dtype=np.uint64))
        eventFid.append(np.zeros(num_clusters, dtype=np.uint32))
        
        for g in range(num_clusters):#For each group
            indices = np.where(groups == g)[0]
            num_in_cluster = len(indices)
            sublist_shot_to_shot =  [list_shot_to_shot[i] for i in indices]
            sublist_image_stats = [list_image_stats[i] for i in indices]
            sublist_physical_units = [list_physical_units[i] for i in indices]
            
            eventTime[j][g] = sublist_shot_to_shot[-1].unixtime
            eventFid[j][g] = sublist_shot_to_shot[-1].fiducial
            distT=[(sublist_image_stats[i][j].xCOM-sublist_image_stats[i][0].xCOM) \
                   *sublist_physical_units[i].xfsPerPix for i in range(num_in_cluster)]
            distE=[(sublist_image_stats[i][j].yCOM-sublist_image_stats[i][0].yCOM) \
                   *sublist_physical_units[i].yMeVPerPix for i in range(num_in_cluster)]
            averageDistT[j][g] = np.mean(distT)
            averageDistE[j][g] = np.mean(distE)
            
            tRMS = [sublist_image_stats[i][j].xRMS*sublist_physical_units[i].xfsPerPix for i in range(num_in_cluster)]  #Conversion to fs and accumulate it in the right group
            eRMS = [sublist_image_stats[i][j].yRMS*sublist_physical_units[i].yMeVPerPix for i in range(num_in_cluster)]
            averageTRMS[j][g] = np.mean(tRMS)
            averageTRMS[j][g] = np.mean(eRMS)
            
            for i in range(num_in_cluster):
                dt_old=sublist_physical_units[i].xfs[1]-sublist_physical_units[i].xfs[0] # dt before interpolation   
                eCurrent=sublist_image_stats[i][j].xProfile/(dt_old*Constants.FS_TO_S)*num_electrons[i]                              #Electron current in electrons/s   

                eCOMslice=(sublist_image_stats[i][j].yCOMslice-sublist_image_stats[i][j].yCOM)*sublist_physical_units[i].yMeVPerPix #Center of mass in energy for each t converted to the right units
                eRMSslice=sublist_image_stats[i][j].yRMSslice*sublist_physical_units[i].yMeVPerPix                                 #Energy dispersion for each t converted to the right units

                interp=scipy.interpolate.interp1d(sublist_physical_units[i].xfs-distT[i],eCurrent,kind='linear',fill_value=0,bounds_error=False,assume_sorted=True)  #Interpolation to master time                    
                averageECurrent[j][g,:]=averageECurrent[j][g,:]+interp(t)  #Accumulate it in the right group                    

                interp=scipy.interpolate.interp1d(sublist_physical_units[i].xfs-distT[i],eCOMslice,kind='linear',fill_value=0,bounds_error=False,assume_sorted=True) #Interpolation to master time
                averageECOMslice[j][g,:]=averageECOMslice[j][g,:]+interp(t)          #Accumulate it in the right group

                interp=scipy.interpolate.interp1d(sublist_physical_units[i].xfs-distT[i],eRMSslice,kind='linear',fill_value=0,bounds_error=False,assume_sorted=True) #Interpolation to master time
                averageERMSslice[j][g,:]=averageERMSslice[j][g,:]+interp(t)

            averageECurrent[j][g,:] = averageECurrent[j][g,:]/num_in_cluster
            averageECOMslice[j][g,:] = averageECOMslice[j][g,:]/num_in_cluster
            averageERMSslice[j][g,:] = averageERMSslice[j][g,:]/num_in_cluster

    return AveragedProfiles(t, averageECurrent, averageECOMslice, 
        averageERMSslice, averageDistT, averageDistE, averageTRMS, 
        averageERMS, num_bunches, eventTime, eventFid)


def oldGroupingMethod(profilesT, num_groups):
    num_profiles = profilesT.shape[0]
    shots_per_group = int(np.ceil(float(num_profiles)/num_groups))
    
    group = np.zeros(num_profiles, dtype=np.int32)       #array that will indicate which group each profile sill correspond to
    group[:]=-1                             #initiated to -1
    for g in range(num_groups):                     #For each group
        currRef=np.where(group==-1)[0]  
        if currRef.size == 0:
            continue
        currRef=currRef[0]                  #We pick the first member to be the first one that has not been assigned to a group yet

        group[currRef]=g                   #We assign it the current group

        # We calculate the correlation of the first profile to the rest of available profiles
        err = np.zeros(num_profiles, dtype=np.float64);              
        for i in range(currRef, num_profiles): 
            if group[i] == -1:
                err[i] = np.corrcoef(profilesT[currRef,:],profilesT[i,:])[0,1]**2;

        #The 'shots_per_group-1' profiles with the highest correlation will be also assigned to the same group
        order=np.argsort(err)            
        for i in range(0, min(shots_per_group-1, len(order))): 
            group[order[-(1+i)]]=g
    return group


def hierarchicalClustering(profilesT, num_clusters, distance='euclidean'):
    linkage = 'ward' if distance == 'euclidean' else 'average'
    model = AgglomerativeClustering(n_clusters=num_clusters, linkage=linkage, affinity=distance)
    model.fit(profilesT)
    return model.labels_


def findOptGroups(X, B, max_num):
    """
    Helper function to find optimal # of groups for profiles 
    Arguments:
      X: profiles to group
      B: number of reference groups to generate
      max_num: maximum number of groups allowed
    Output
      opt: the optimal number of groups for this data
    """
    num_profiles, t = X.shape
    rand_cluster_variance = {}
    true_cluster_variance = {}
    sd = {}
    #svd of profiles matrix
    column_mean = np.mean(X, axis=0)
    centered = X - column_mean
    u,d,vt = np.linalg.svd(centered)
    x_ = np.matmul(centered, vt.T)
    bounding_box = getBoundingBox(x_)
    min_clusters = 2
    max_clusters = max_num
    gap_statistic = {}
    sd = {}
    reference_sets = []
    for i in range(B):
        rand_sample = generateRandSample(bounding_box, num_profiles)
        rand_sample = np.matmul(rand_sample, vt) + column_mean
        reference_sets.append(rand_sample)
        
    gap_statistic[min_clusters], sd[min_clusters] = calcGapStatistic(min_clusters, X, reference_sets)
    gap_statistic[max_clusters], sd[max_clusters] = calcGapStatistic(max_clusters, X, reference_sets)
    while True:
        mid1 = (max_clusters - min_clusters)/2 + min_clusters
        if mid1 == max_clusters or mid1 == min_clusters:
            break
        if not gap_statistic.get(mid1):
            gap_statistic[mid1], sd[mid1] = calcGapStatistic(mid1, X, reference_sets)
        if not gap_statistic.get(mid1-1):
            gap_statistic[mid1-1], sd[mid1-1] = calcGapStatistic(mid1-1, X, reference_sets)
        if gap_statistic[mid1] - sd[mid1] < gap_statistic[mid1-1]:
            max_clusters = mid1
        else:
            min_clusters = mid1
    opt = max_clusters if gap_statistic[max_clusters] - sd[max_clusters] > gap_statistic[max_clusters -1] else min_clusters
    return opt


def calcGapStatistic(n, X, reference_sets):
    B = len(reference_sets)
    model = AgglomerativeClustering(n_clusters=n, linkage="ward", affinity="euclidean")
    model.fit(X)
    true_cluster_variance = np.log(calcClusterVariance(model.labels_, X, n))
    rand_variance = []
    num_profiles = X.shape[0]
    #generate B random reference datasets
    for k in range(B):        
        model.fit(reference_sets[k])
        rand_variance.append(np.log(calcClusterVariance(model.labels_, reference_sets[k], n)))
    rand_cluster_variance = np.mean(rand_variance)
    sd = np.std(rand_variance)* np.sqrt(1+1./B)
    gap_statistic = rand_cluster_variance - true_cluster_variance
    return gap_statistic, sd


def calcClusterVariance(assignments, data, num_clusters):
    d = 0
    for group in range(num_clusters):
        points = data[assignments == group,:]
        center = np.mean(points, axis = 0)
        d += sum(np.apply_along_axis(lambda x: np.linalg.norm(x - center)**2, 1, points))
    return d


def generateRandSample(bounding_box, num_profiles):
    return np.apply_along_axis(lambda l : np.random.uniform(l[0], l[1], num_profiles), 1, bounding_box).T


def getBoundingBox(X):
    return [(min(X[:,i]), max(X[:,i])) for i in range(X.shape[1])]

# http://stackoverflow.com/questions/26248654/numpy-return-0-with-divide-by-zero
def divideNoWarn(numer,denom,default):
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio=numer/denom
        ratio[ ~ np.isfinite(ratio)]=default  # NaN/+inf/-inf 
    return ratio


def namedtuple(typename, field_names, default_values=()):
    """
    Overwriting namedtuple class to use default arguments for variables not passed in at creation of object
    Can manually set default value for a variable; otherwise None will become default value
    """
    T = collections.namedtuple(typename, field_names)
    T.__new__.__defaults__ = (None,) * len(T._fields)

    if isinstance(default_values, collections.Mapping):
        prototype = T(**default_values)
    else:
        prototype = T(*default_values)

    T.__new__.__defaults__ = tuple(prototype)
    return T

      
ShotToShotParameters = namedtuple('ShotToShotParameters',
    ['ebeamcharge',  #ebeamcharge
    'dumpecharge',  #dumpecharge in C
    'xtcavrfamp',   #RF amplitude
    'xtcavrfphase', #RF phase
    'xrayenergy',   #Xrays energy in J
    'unixtime',
    'fiducial',
    'valid'],
    {'ebeamcharge': Constants.E_BEAM_CHARGE,
    'dumpecharge': Constants.DUMP_E_CHARGE,
    'xtcavrfphase': Constants.XTCAV_RFPHASE,
    'xtcavrfamp': Constants.XTCAV_RFAMP,
    'xrayenergy': 1e-3*Constants.ENERGY_DETECTOR,
    'valid': 1}
    )


ImageStatistics = namedtuple('ImageStatistics', 
    ['imfrac',
    'xProfile',
    'yProfile',
    'xCOM',
    'yCOM',
    'xRMS',
    'yRMS',
    'xFWHM',
    'yFWHM',
    'yCOMslice',
    'yRMSslice'],
    {'xRMS': 0,
     'yRMS': 0,
     'xFWHM': 0,
     'yFWHM': 0,
     })


PhysicalUnits = namedtuple('PhysicalUnits', 
    ['xfs',
    'yMeV',
    'xfsPerPix',
    'yMeVPerPix',
    'valid'])


AveragedProfiles = namedtuple('AveragedProfiles',
    ['t',                         #Master time in fs
    'eCurrent',                   #Electron current in (#electrons/s)
    'eCOMslice',                  #Energy center of masses for each time in MeV
    'eRMSslice',                  #Energy dispersion for each time in MeV
    'distT',                      #Distance in time of the center of masses with respect to the center of the first bunch in fs
    'distE',                      #Distance in energy of the center of masses with respect to the center of the first bunch in MeV
    'tRMS',                       #Total dispersion in time in fs
    'eRMS',                       #Total dispersion in energy in MeV
    'num_bunches',                #Number of bunches
    'eventTime',                  #Unix times used for jumping to events
    'eventFid'])                  #Fiducial values used for jumping to events

PulseCharacterization = namedtuple('PulseCharacterization',
    ['t',                        #Master time vector in fs
    'powerrawECOM',              #Retrieved power in GW based on ECOM without gas detector normalization
    'powerrawERMS',              #Retrieved power in arbitrary units based on ERMS without gas detector normalization
    'powerECOM',                 #Retrieved power in GW based on ECOM
    'powerERMS',                 #Retrieved power in GW based on ERMS
    'powerAgreement',            #Agreement between the two intensities
    'bunchdelay',                #Delay from each bunch with respect to the first one in fs
    'bunchdelaychange',          #Difference between the delay from each bunch with respect to the first one in fs and the same form the non lasing reference
    'xrayenergy',                #Total x-ray energy from the gas detector in J
    'lasingenergyperbunchECOM',  #Energy of the XRays generated from each bunch for the center of mass approach in J
    'lasingenergyperbunchERMS',  #Energy of the XRays generated from each bunch for the dispersion approach in J
    'bunchenergydiff',           #Distance in energy for each bunch with respect to the first one in MeV
    'bunchenergydiffchange',     #Comparison of that distance with respect to the no lasing
    'lasingECurrent',            #Electron current for the lasing trace (In #electrons/s)
    'nolasingECurrent',          #Electron current for the no lasing trace (In #electrons/s)
    'lasingECOM',                #Lasing energy center of masses for each time in MeV
    'nolasingECOM',              #No lasing energy center of masses for each time in MeV
    'lasingERMS',                #Lasing energy dispersion for each time in MeV
    'nolasingERMS',              #No lasing energy dispersion for each time in MeV
    'num_bunches',               #Number of bunches
    'groupnum'                   #group number of lasing-off shot
    ])

ROIMetrics = namedtuple('ROIMetrics',
    ['xN', #Size of the image in X   
    'x0',  #Position of the first pixel in x
    'yN',  #Size of the image in Y 
    'y0',  #Position of the first pixel in y
    'x',   #X vector
    'y',   #Y vector
    ], 
    {'xN': 1024,                      
     'x0': 0, 
     'yN': 1024, 
     'y0': 0,
     'x': np.arange(0, 1024),
     'y': np.arange(0, 1024)})


GlobalCalibration = namedtuple('GlobalCalibration', 
    ['umperpix', #Pixel size of the XTCAV camera
    'strstrength', #Strength parameter
    'rfampcalib', #Calibration of the RF amplitude
    'rfphasecalib', #Calibration of the RF phase
    'dumpe',        #Beam energy: dump config
    'dumpdisp'])


ImageProfile = namedtuple('ImageProfile', 
    ['image_stats',
    'roi',
    'shot_to_shot',
    'physical_units'])
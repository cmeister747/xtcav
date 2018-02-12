import copy
import os
import time
import psana
import numpy as np
import glob
import sys
import getopt
import warnings
import Utils as xtu
import UtilsPsana as xtup
from FileInterface import Load as constLoad
from FileInterface import Save as constSave
from DarkBackground import *
from CalibrationPaths import *
import Constants
from Metrics import *
  
"""
    Class that generates a dark background image for XTCAV reconstruction purposes
    Arguments:
        experiment (str): String with the experiment reference to use. E.g. 'amoc8114'
        run (str): String with a run number. E.g. '123' 
        maxshots (int): Maximum number of images to use for the reference.
        calibrationpath (str): Custom calibration directory in case the default is not intended to be used.
        validityrange (tuple): If not set, the validity range for the reference will go from the 
        first run number used to generate the reference and the last run.
"""

class DarkBackground(object):
    def __init__(self, 
        experiment='amoc8114', 
        maxshots=401, 
        run_number='86', 
        validityrange=None, 
        calibrationpath=''):

        self.image=[]
        self.ROI=None
        self.run=''
        self.n=0

        self.parameters = DarkBackgroundParameters(
            experiment = experiment, maxshots = maxshots, run = run_number, 
            validityrange = validityrange, calibrationpath = calibrationpath)

    def Generate(self, savetofile=True):
        
        warnings.filterwarnings('always',module='Utils',category=UserWarning)
        warnings.filterwarnings('ignore',module='Utils',category=RuntimeWarning, message="invalid value encountered in divide")
        
        """
        After setting all the parameters, this method has to be called to generate the dark reference and 
        save it in the proper location. 
        """
        print 'dark background reference'
        print '\t Experiment: %s' % self.parameters.experiment
        print '\t Run: %s' % self.parameters.run
        print '\t Valid shots to process: %d' % self.parameters.maxshots
        
        #Loading the dataset from the "dark" run, this way of working should be compatible with both xtc and hdf5 files
        dataSource=psana.DataSource("exp=%s:run=%s:idx" % (self.parameters.experiment, self.parameters.run))
        
        #Camera and type for the xtcav images
        xtcav_camera = psana.Detector(Constants.SRC)
        
        #Stores for environment variables    
        configStore=dataSource.env().configStore()
        epicsStore=dataSource.env().epicsStore()

        n=0  #Counter for the total number of xtcav images processed 
        run = dataSource.runs().next()        
        
        ROI_XTCAV, last_image = xtup.GetXTCAVImageROI(epicsStore, run, xtcav_camera)
        accumulator_xtcav = np.zeros((ROI_XTCAV.yN, ROI_XTCAV.xN), dtype=np.float64)

        times = run.times()
        for t in range(last_image,-1,-1): #Starting from the last valid image, to avoid waits in the cases where there are not xtcav images for the first shots
            evt=run.event(times[t])
        
            #ignore shots without xtcav, because we can get incorrect EPICS information (e.g. ROI).  this is
            #a workaround for the fact that xtcav only records epics on shots where it has camera data, as well
            #as an incorrect design in psana where epics information is not stored per-shot (it is in a more global object
            #called "Env")
            img = xtcav_camera.image(evt)
            # skip if empty image
            if img is None: 
                continue
          
            accumulator_xtcav += img 
            n += 1
                
            if n % 5 == 0:
                sys.stdout.write('\r%.1f %% done, %d / %d' % ( float(n) / self.parameters.maxshots*100, n, self.parameters.maxshots ))
                sys.stdout.flush()   
            if n >= self.parameters.maxshots:                    #After a certain number of shots we stop (Ideally this would be an argument, rather than a hardcoded value)
                sys.stdout.write('\n')
                break                          
        #At the end of the program the total accumulator is saved  
        self.image=accumulator_xtcav/n
        self.ROI=ROI_XTCAV
        
        if not self.parameters.validityrange:
            self.parameters = self.parameters._replace(validityrange=[self.parameters.run, 'end'])
        
        cp = CalibrationPaths(dataSource.env(), self.parameters.calibrationpath)
        ### what is pedestals?
        file = cp.newCalFileName('pedestals', self.parameters.validityrange[0], self.parameters.validityrange[1])
        
        if savetofile:
            self.Save(file)

    def Save(self,path): 
        # super hacky... allows us to save without overwriting current instance
        instance = copy.deepcopy(self)
        if instance.ROI:
            instance.ROI = dict(vars(instance.ROI))
            instance.parameters = dict(instance.parameters._asdict())
        constSave(instance,path)
        
    @staticmethod    
    def Load(path):        
        db = constLoad(path)
        db.ROI = ROIMetrics(db.ROI['xN'], db.ROI['x0'], db.ROI['yN'], db.ROI['y0'], x=db.ROI['x'], y=db.ROI['y'])
        return db

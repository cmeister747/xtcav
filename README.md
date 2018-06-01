# XTCAV Analysis

XTCAV is a detector that is used to determine the laser-power vs. time of each LCLS shot.  Some detailed documentation from Tim Maxwell on this device is Here****.  Alvaro Sanchez-Gonzalez authored the original psana-python code to do the rather complex analysis of images from the XTCAV camera to determine these quantities.  This current version has been updated to run more quickly and to fix some analysis errors.  

These scripts use some XTCAV data that was made public so they should be runnable by all users.  The scripts can be found in /reg/g/psdm/tutorials/examplePython/xtcav/ in the files xtcavDark.py, xtcavLasingOff.py, xtcavLasingOn.py.

## Quickstart

Two things must be done before XTCAV analysis will function: a "dark run" must be analyzed to get the pedestal values for cameras, and a "no lasing" run must be analyzed to generate sets of "no lasing" images (the latter is quite a complex process).  Note that for demonstration these first two scripts write constants to a "local" calibration directory called "calib".  For a real-experiment you won't need these lines because you will have permission to write to your official experiment calibration-constants directory.

Sample of dark run analysis:

```
# these two lines for example purposes only, to allow user to write
# calibration information to local directory called "calib"
# should be deleted for real analysis.

import psana
psana.setOption('psana.calib-dir','calib')
from xtcav.DarkBackground import *

DarkBackground(experiment='xpptut15', 
	run_number='300', 
	max_shots=1000,
	validity_range=(300,302))
```

Sample of "no-lasing" reference generating script:
```
# these two lines for example purposes only, to allow user to write
# calibration information to local directory called "calib"
# should be deleted for real analysis.
import psana
psana.setOption('psana.calib-dir','calib')
from xtcav.LasingOffReference import *
LasingOffReference(
	experiment='xpptut15',
	run_number='301',
	max_shots=1400,
	num_bunches=1,
	island_split_method = 'scipyLabel',
	validity_range=(300,302)) #only give first run number to have the validity range be open-ended ("end")

```


This script assumes that dark/lasing-off data has been analyzed (see above).  Unlike the previous two scripts it reads dark/lasing-off constants from the official calibration-directory. 

```
from psana import *
import matplotlib.pyplot as plt
from xtcav.LasingOnCharacterization import *
experiment = 'xpptut15'
run = '302'
mode = 'smd'
ds = psana.DataSource("exp=%s:run=%s:%s" % (experiment, run, mode))
ngood = 0

XTCAVRetrieval=LasingOnCharacterization() 

for evt in ds.events():
    if not XTCAVRetrieval.processEvent(evt):
        continue

    # time and power are lists, with each entry corresponding to
    # a bunch number.  The number of bunches is set by the GLOC.nb
    # parameter in the lasing-off analysis.  In general, one should
    # also cut on the "agreement" value, which measures the agreement
    # between the first and second moment analysis (larger is better).
    time, power = XTCAVRetrieval.xRayPower()  
    agreement = XTCAVRetrieval.reconstructionAgreement()

    ngood += 1
    print 'Agreement: %g%% ' % (agreement*100)
    plt.plot(time[0],power[0])
    plt.xlabel('Time (fs)')
    plt.ylabel('Lasing Power (GW)')
    plt.title('Agreement %4.2f'%agreement)
    plt.show()
    if ngood > 1: 
        break
    
```

The LasingOnCharacerization module uses the detector interface **insert link** to find the datasource being used. The program will fail if you try to process events without first setting a datasource.

**Talk about mode**

### Prerequisites

What things you need to install the software and how to install them

```
Give examples
```

### Installing

A step by step series of examples that tell you have to get a development env running

Say what the step will be

```
Give the example
```

And repeat

```
until finished
```

End with an example of getting some data out of the system or using it for a little demo

## Running the tests

Explain how to run the automated tests for this system

### Break down into end to end tests

Explain what these tests test and why

```
Give an example
```

### And coding style tests

Explain what these tests test and why

```
Give an example
```

## Deployment

Add additional notes about how to deploy this on a live system


## Versioning



## Authors




.. image:: https://requires.io/github/Dennis-van-Gils/project-e-coli-sauna/requirements.svg?branch=master
    :target: https://requires.io/github/Dennis-van-Gils/project-e-coli-sauna/requirements/?branch=master
    :alt: Requirements Status
.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black
.. image:: https://img.shields.io/badge/License-MIT-purple.svg
    :target: https://github.com/Dennis-van-Gils/project-e-coli-sauna/blob/master/LICENSE.txt

E. coli sauna
=============
*A Physics of Fluids project.*

A miniature sauna for happy E. coli. A temperature controlled box with humidity
logging made from an Adafruit ItsyBitsy M4 Express micro-controller board, a
DHT22 sensor and an Aim TTi digital power supply powering two Kapton film
heaters.

- Github: https://github.com/Dennis-van-Gils/project-e-coli-sauna

.. image:: https://raw.githubusercontent.com/Dennis-van-Gils/project-e-coli-sauna/master/images/screenshot.png

Instructions
============
Download the `latest release <https://github.com/Dennis-van-Gils/project-e-coli-sauna/releases/latest>`_
and unpack to a folder onto your drive. The electronic diagram can be found at
`doc/elecronic_diagram.pdf <https://raw.githubusercontent.com/Dennis-van-Gils/project-e-coli-sauna/master/docs/electronic_diagram.pdf>`_.

Flashing the firmware
---------------------

Double click the reset button of the ItsyBitsy while plugged into your PC. This
will mount a drive called `ITSYM4BOOT`. Copy
`src_mcu/_build_ItsyBitsy_M4/CURRENT.UF2 <https://github.com/Dennis-van-Gils/project-e-coli-sauna/raw/master/src_mcu/_build_ItsyBitsy_M4/CURRENT.UF2>`_
onto the BOOT drive. It will restart automatically with the new firmware.

Running the application
-----------------------

Preferred Python distributions:
    * `Anaconda <https://www.anaconda.com>`_
    * `Miniconda <https://docs.conda.io/en/latest/miniconda.html>`_

Open `Anaconda Prompt` and navigate to the unpacked folder. Run the following to
install the necessary packages: ::

    cd src_python
    pip install -r requirements.txt
    
Now you can run the application: ::

    python main.py

LED status lights
=================

* Solid blue: Booting and setting up
* Solid green: Ready for communication
* Flashing green: Sensor data is being send over USB

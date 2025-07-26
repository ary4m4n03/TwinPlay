# <img src="screenshots/TwinPlay.png" height="32"> TwinPlay
![Python](https://img.shields.io/badge/python-3.x-blue.svg) ![Platform](https://img.shields.io/badge/platform-Windows-0078D6.svg) ![License](https://img.shields.io/badge/license-MIT-green.svg)  

**TwinPlay** is a lightweight Windows utility that lets you output audio to two devices at the same time. Perfect for sharing sound between speakers and headphones, or syncing playback across different outputs.

---

## Table of Contents
- [Features](#features)
- [Screenshots](#screenshots)
- [Installation](#installation)
- [Usage](#usage)
- [Dependencies](#dependencies)

---

## Features
* **Dual Audio Output:** Stream audio to two output devices simultaneously.
* **Simple Interface:** A clean and intuitive UI built with Python and Tkinter.
* **Device Selection:** Easily select your desired primary and secondary audio devices from dropdown menus.
* **Real-time Control:** Start and stop audio routing with a single click.
* **Lightweight:** Minimal resource footprint, designed specifically for Windows.

---

## Screenshots

Dropdown Menu:

![alt text](https://github.com/ary4m4n03/TwinPlay/blob/main/screenshots/dropdown.png?raw=true)

Ready:

![alt text](https://github.com/ary4m4n03/TwinPlay/blob/main/screenshots/ready.png?raw=true)

Routing Audio:

![alt text](https://github.com/ary4m4n03/TwinPlay/blob/main/screenshots/routing.png?raw=true)

Stopped:

![alt text](https://github.com/ary4m4n03/TwinPlay/blob/main/screenshots/stopped.png?raw=true)

---

## Installation
You can get TwinPlay up and running in two ways.

### Method 1: Download from Releases (Recommended)
1.  Go to the project's [**Releases**](https://github.com/ary4m4n03/TwinPlay/releases) page.
2.  Download the latest `TwinPlay.exe` file from the latest release.
3.  Run `TwinPlay.exe`. No installation is required!

### Method 2: From Source (For developers)
1.  Ensure you have **Python 3.8+** installed.
2.  Clone this repository:
    ```bash
    git clone https://github.com/ary4m4n03/TwinPlay.git
    ```
3.  Navigate into the project directory:
    ```bash
    cd TwinPlay
    ```
4.  Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```
5.  Install as an .exe:
    ```bash
    pyinstaller --onefile -w 'filename.py'
    ```
---

## Usage
Using TwinPlay is straightforward:

1.  **Launch the application** by running `TwinPlay.exe` or `python main.py` if you installed from source.
2.  From the **"Primary Device"** dropdown, select the audio output you want to capture (e.g., your default speakers).
3.  From the **"Secondary Device"** dropdown, select the device you want to duplicate the audio to (e.g., your headphones).
4.  Click the **"Start Routing"** button. The status will change to "Routing Audio...".
5.  Play any audio on your computer. You should now hear it from both selected devices!
6.  To stop, simply click the **"Stop Routing"** button.
---

## Dependencies
This project is built with Python and relies on the following major libraries:

* **Tkinter:** For the user interface.
* **pycaw:** For controlling audio devices on Windows.
* **pyaudio:** For audio stream handling.



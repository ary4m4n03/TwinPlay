import tkinter as tk
from tkinter import ttk, messagebox
import threading

# Assume list_audio_devices and AudioRouter classes are defined as above

import pyaudiowpatch as pyaudio # Assuming pyaudiowpatch is installed

import pyaudiowpatch as pyaudio
import numpy as np
import threading
import time

# Helper function to get supported rates (keep this from previous discussion)
def get_supported_sample_rates_for_device(p, device_index, input_or_output='output'):
    """Tests common sample rates for a given device."""
    info = p.get_device_info_by_index(device_index)
    supported_rates = []
    common_rates = [44100, 48000, 96000, 88200, 192000]

    for rate in common_rates:
        try:
            format = pyaudio.paInt16
            channels = 1 # Start with mono to maximize compatibility for testing
            if input_or_output == 'output' and info['maxOutputChannels'] >= 2:
                channels = 2
            elif input_or_output == 'input' and info['maxInputChannels'] >= 2:
                channels = 2

            if input_or_output == 'output':
                stream = p.open(
                    format=format,
                    channels=channels,
                    rate=rate,
                    output=True,
                    frames_per_buffer=1024,
                    output_device_index=device_index
                )
            else: # input or loopback
                stream = p.open(
                    format=format,
                    channels=channels,
                    rate=rate,
                    input=True,
                    frames_per_buffer=1024,
                    input_device_index=device_index
                )
            
            stream.stop_stream()
            stream.close()
            supported_rates.append(rate)
        except Exception as e:
            pass # Don't print for every unsupported rate
    return supported_rates

class AudioRouter:
    def __init__(self, primary_device_index, secondary_device_index):
        self.p = pyaudio.PyAudio()
        self.primary_device_index = primary_device_index
        self.secondary_device_index = secondary_device_index
        self.stream = None # Loopback input stream
        self.primary_output_stream = None
        self.secondary_output_stream = None
        self.running = False
        self.thread = None

        try:
            self.primary_info = self.p.get_device_info_by_index(self.primary_device_index)
            self.secondary_info = self.p.get_device_info_by_index(self.secondary_device_index)
        except OSError as e:
            raise Exception(f"Could not get device info for selected devices. Check indices. Error: {e}")

        print(f"\nSelected Primary Device: {self.primary_info['name']} (Index: {self.primary_info['index']})")
        print(f"Selected Secondary Device: {self.secondary_info['name']} (Index: {self.secondary_info['index']})")

        # Find the loopback device for the primary output device
        self.loopback_device_index = None
        wasapi_info = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
        
        # Iterating through all devices to find the one marked as loopback AND matches primary
        found_loopback_for_primary = False
        for i in range(self.p.get_device_count()):
            info = self.p.get_device_info_by_index(i)
            
            # Check if it's a WASAPI loopback device and its name contains the primary device's name
            if info.get('isLoopbackDevice') and info['hostApi'] == wasapi_info['index'] and \
               self.primary_info['name'] in info['name']:
                self.loopback_device_index = info['index']
                self.loopback_info = info
                found_loopback_for_primary = True
                print(f"Found loopback device for primary: {self.loopback_info['name']} (Index: {self.loopback_device_index})")
                break
        
        if not found_loopback_for_primary:
            raise Exception(f"Could not find a WASAPI loopback device for primary output: {self.primary_info['name']}")

        # Determine common audio parameters based on the loopback device
        # The loopback's properties tell us what it will output
        self.common_sample_rate = int(self.loopback_info['defaultSampleRate'])
        self.common_channels = self.loopback_info['maxInputChannels'] # Loopback maxInputChannels is its output channels
        self.common_format = pyaudio.paInt16 # Using 16-bit integer format

        # Add a check that the secondary device actually supports this rate and channels
        secondary_supported_rates = get_supported_sample_rates_for_device(self.p, self.secondary_device_index, 'output')
        
        if self.common_sample_rate not in secondary_supported_rates:
            print(f"WARNING: Secondary device '{self.secondary_info['name']}' does not directly support the primary loopback sample rate ({self.common_sample_rate} Hz).")
            # Fallback strategy: find a common rate
            fallback_rates = [48000, 44100] # Prioritize 48kHz, then 44.1kHz
            found_fallback = False
            for rate in fallback_rates:
                if rate in secondary_supported_rates and self.p.is_format_supported(
                    self.common_sample_rate, # The rate we will use for loopback
                    self.common_channels,   # The channels we will use for loopback
                    self.common_format,
                    input_device=self.loopback_device_index
                ) and self.p.is_format_supported(
                    rate,
                    self.common_channels,
                    self.common_format,
                    output_device=self.secondary_device_index
                ):
                    self.common_sample_rate = rate
                    found_fallback = True
                    print(f"Falling back to {self.common_sample_rate} Hz for all streams.")
                    break
            if not found_fallback:
                raise Exception(f"No mutually supported sample rate found between primary loopback and secondary device. Consider using 44100Hz or 48000Hz for both.")
        
        # Validate channels: secondary device must support at least common_channels
        if self.secondary_info['maxOutputChannels'] < self.common_channels:
             # This is a more severe issue, might need to downmix or raise error
             print(f"WARNING: Secondary device '{self.secondary_info['name']}' only supports {self.secondary_info['maxOutputChannels']} output channels, but primary loopback provides {self.common_channels}. Attempting to use primary channels.")
             # You might need to add logic here to downmix if channels mismatch and it causes issues.
             # For now, we'll try to push common_channels. PyAudio might handle it or error.
             # self.common_channels = min(self.common_channels, self.secondary_info['maxOutputChannels'])

        print(f"Audio parameters chosen: Rate={self.common_sample_rate} Hz, Channels={self.common_channels}, Format={self.common_format}")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        audio_data = np.frombuffer(in_data, dtype=np.int16) 

        # REMOVE THIS BLOCK
        # if self.primary_output_stream and self.primary_output_stream.is_active():
        #     try:
        #         self.primary_output_stream.write(audio_data.tobytes())
        #     except Exception as e:
        #         print(f"Error writing to primary device in callback: {e}")

        # This is the only output you need
        if self.secondary_output_stream and self.secondary_output_stream.is_active():
            try:
                self.secondary_output_stream.write(audio_data.tobytes())
            except Exception as e:
                print(f"Error writing to secondary device in callback: {e}")

        return (in_data, pyaudio.paContinue)

    def start_routing(self):
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_routing, daemon=True)
        self.thread.start()

    def _run_routing(self):
        try:
            # REMOVE THIS BLOCK if the primary device is already playing
            # If you remove this, the primary device continues to play Audio
            # directly, and your app only adds the secondary device.
            # self.primary_output_stream = self.p.open(
            #     format=self.common_format,
            #     channels=self.common_channels,
            #     rate=self.common_sample_rate,
            #     output=True,
            #     output_device_index=self.primary_device_index,
            #     frames_per_buffer=1024
            # )
            # print(f"Opened primary output stream on {self.primary_info['name']}")

            # Open the secondary output stream (this is the one you NEED)
            self.secondary_output_stream = self.p.open(
                format=self.common_format,
                channels=self.common_channels,
                rate=self.common_sample_rate,
                output=True,
                output_device_index=self.secondary_device_index,
                frames_per_buffer=1024
            )
            print(f"Opened secondary output stream on {self.secondary_info['name']}")

            # Open the loopback input stream (this is your source)
            self.stream = self.p.open(
                format=self.common_format,
                channels=self.common_channels,
                rate=self.common_sample_rate,
                input=True,
                input_device_index=self.loopback_device_index,
                frames_per_buffer=1024,
                stream_callback=self._audio_callback
            )
            print(f"Opened loopback input stream on {self.loopback_info['name']}")
            print("Audio routing started...")

            while self.running and self.stream.is_active():
                time.sleep(0.1) 
        except Exception as e:
            print(f"Error during audio routing: {e}")
            self.running = False 
        finally:
            self._cleanup_streams()
            print("Audio routing thread finished.")

    def stop_routing(self):
        if not self.running:
            return
        self.running = False
        print("Signaled audio routing to stop...")
        
        if threading.current_thread() != self.thread and self.thread and self.thread.is_alive():
             self.thread.join(timeout=2)
             if self.thread.is_alive():
                 print("Warning: Audio routing thread did not terminate gracefully.")
        self.thread = None

    def _cleanup_streams(self):
        # Stop and close loopback input stream
        if self.stream and self.stream.is_active():
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

        # Stop and close primary output stream
        if self.primary_output_stream and self.primary_output_stream.is_active():
            self.primary_output_stream.stop_stream()
            self.primary_output_stream.close()
            self.primary_output_stream = None

        # Stop and close secondary output stream
        if self.secondary_output_stream and self.secondary_output_stream.is_active():
            self.secondary_output_stream.stop_stream()
            self.secondary_output_stream.close()
            self.secondary_output_stream = None
        
        print("Audio streams closed.")

    def shutdown(self):
        self.stop_routing()
        if self.p:
            self.p.terminate()
            self.p = None
        print("PyAudio terminated.")

    def __del__(self):
        if self.p:
            self.shutdown()


import pyaudiowpatch as pyaudio
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

def list_audio_devices():
    p = pyaudio.PyAudio()
    devices = []
    try:
        # Get host API info for WASAPI
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError:
        print("WASAPI not available.")
        wasapi_info = None

    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        
        device_name = info['name']
        device_index = info['index']
        device_is_loopback = False

        # Check for loopback devices specific to PyAudioWPatch
        # PyAudioWPatch often adds an 'isLoopbackDevice' key or a clear naming convention
        if info.get('isLoopbackDevice'):
            device_is_loopback = True
        elif wasapi_info and info['hostApi'] == wasapi_info['index'] and '[Loopback]' in device_name:
            device_is_loopback = True

        # Use .get() with a default value of 0 for channel counts
        max_output_channels = info.get('maxOutputChannels', 0)
        max_input_channels = info.get('maxInputChannels', 0)

        # Only add devices that have *some* output or input capability
        if max_output_channels > 0 or max_input_channels > 0:
            devices.append({
                'name': device_name,
                'index': device_index,
                'is_loopback': device_is_loopback,
                'maxOutputChannels': max_output_channels, # Store the actual value or 0
                'maxInputChannels': max_input_channels    # Store the actual value or 0
            })
    p.terminate()
    return devices

# Example usage:
# all_devices = list_audio_devices()
# for device in all_devices:
#     print(f"Name: {device['name']}, Index: {device['index']}, Loopback: {device['is_loopback']}")





import tkinter as tk
from tkinter import ttk, messagebox
import threading

# Assume list_audio_devices and AudioRouter classes are defined as above
# (with the changes to AudioRouter to *not* re-route to the primary output)

class AudioSplitterApp:
    def __init__(self, master):
        self.master = master
        master.title("Dual Audio Output")

        self.audio_router = None
        self.devices = list_audio_devices() # Call the helper function to get device list

        self.primary_device_var = tk.StringVar(master)
        self.secondary_device_var = tk.StringVar(master)

        self.setup_gui()

    def setup_gui(self):
        # Primary Device Selection (This is the device that Spotify/apps will play to)
        ttk.Label(self.master, text="Audio Source Device (e.g., Speakers):").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.primary_device_dropdown = ttk.Combobox(self.master, textvariable=self.primary_device_var, state="readonly")
        # Now, d['maxOutputChannels'] will always exist, even if 0
        self.primary_device_dropdown['values'] = [d['name'] for d in self.devices if not d['is_loopback'] and d['maxOutputChannels'] > 0]
        self.primary_device_dropdown.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.primary_device_dropdown.bind("<<ComboboxSelected>>", self.on_primary_device_selected)

        # ... (secondary device) ...
        # Secondary Device Selection (This is where your app will route the audio)
        ttk.Label(self.master, text="Secondary Output Device (e.g., Bluetooth Headphones):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.secondary_device_dropdown = ttk.Combobox(self.master, textvariable=self.secondary_device_var, state="readonly")
        self.secondary_device_dropdown['values'] = [d['name'] for d in self.devices if not d['is_loopback'] and d['maxOutputChannels'] > 0]
        self.secondary_device_dropdown.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        self.secondary_device_dropdown.bind("<<ComboboxSelected>>", self.on_secondary_device_selected)

        # Start/Stop Buttons
        self.start_button = ttk.Button(self.master, text="Start Routing", command=self.start_routing)
        self.start_button.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        self.stop_button = ttk.Button(self.master, text="Stop Routing", command=self.stop_routing, state=tk.DISABLED)
        self.stop_button.grid(row=2, column=1, padx=10, pady=10, sticky="ew")
        
        # Status Label
        self.status_label = ttk.Label(self.master, text="Status: Ready")
        self.status_label.grid(row=3, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        # Initial device selection (optional, but good for user experience)
        if len(self.devices) > 0:
            # Try to pre-select the default output device as the primary source
            default_output_device_name = self.get_default_output_device_name()
            if default_output_device_name:
                self.primary_device_var.set(default_output_device_name)
                self.on_primary_device_selected(None) # Manually call handler

            # Try to pre-select a different device for secondary if available
            available_for_secondary = [d['name'] for d in self.devices if not d['is_loopback'] and d['name'] != self.primary_device_var.get() and d['maxOutputChannels'] > 0]
            if available_for_secondary:
                # Try to pick a Bluetooth device if available and not the primary
                bluetooth_device = next((name for name in available_for_secondary if "bluetooth" in name.lower()), None)
                if bluetooth_device:
                    self.secondary_device_var.set(bluetooth_device)
                else:
                    self.secondary_device_var.set(available_for_secondary[0])
                self.on_secondary_device_selected(None)

    def get_default_output_device_name(self):
        """Helper to find the currently set default output device name."""
        try:
            import pycaw.pycaw as pycaw
            sessions = pycaw.AudioUtilities.GetAllSessions()
            for session in sessions:
                if session.Process and session.Process.name() == "System": # System sounds often use default
                    endpoint = session.GetAudioEndpoint()
                    if endpoint:
                        props = endpoint.GetProperties()
                        # PKEY_Device_FriendlyName from mmdeviceapi.h
                        # Use the specific property key for friendly name
                        # This might vary slightly based on pycaw version/Windows.
                        # A more robust way might be to iterate devices in PyAudio and find the default.
                        p = pyaudio.PyAudio()
                        default_output_index = p.get_default_output_device_info()['index']
                        p.terminate()
                        
                        default_device = next((d for d in self.devices if d['index'] == default_output_index), None)
                        if default_device:
                            return default_device['name']
            # Fallback if pycaw doesn't easily give it or isn't used
            p = pyaudio.PyAudio()
            default_output_index = p.get_default_output_device_info()['index']
            p.terminate()
            default_device = next((d for d in self.devices if d['index'] == default_output_index), None)
            if default_device:
                return default_device['name']

        except Exception as e:
            print(f"Could not get default output device name via pycaw/pyaudio: {e}")
        return None


    def on_primary_device_selected(self, event):
        selected_name = self.primary_device_var.get()
        # Allow primary and secondary to be the same initially,
        # but the logic in AudioRouter will prevent feedback
        # by not re-routing to primary. However, it might not make sense UX-wise.
        # It's better to prevent selecting the same device for primary & secondary in the GUI.
        if selected_name == self.secondary_device_var.get() and selected_name != "":
            messagebox.showwarning("Warning", "The audio source device and secondary output device cannot be the same.")
            self.primary_device_var.set("") # Clear selection
            self.primary_selected_index = None
        else:
            self.primary_selected_index = next((d['index'] for d in self.devices if d['name'] == selected_name), None)

    def on_secondary_device_selected(self, event):
        selected_name = self.secondary_device_var.get()
        if selected_name == self.primary_device_var.get() and selected_name != "":
            messagebox.showwarning("Warning", "The audio source device and secondary output device cannot be the same.")
            self.secondary_device_var.set("") # Clear selection
            self.secondary_selected_index = None
        else:
            self.secondary_selected_index = next((d['index'] for d in self.devices if d['name'] == selected_name), None)

    def start_routing(self):
        if not self.primary_selected_index or not self.secondary_selected_index:
            messagebox.showerror("Error", "Please select both an audio source device and a secondary output device.")
            return

        try:
            self.status_label.config(text="Status: Starting...")
            # AudioRouter is initiated with the two selected device indices
            self.audio_router = AudioRouter(self.primary_selected_index, self.secondary_selected_index)
            self.audio_router.start_routing()
            self.status_label.config(text="Status: Routing audio...")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start routing: {e}\nEnsure your selected source device is the active output for audio applications like Spotify.")
            self.status_label.config(text="Status: Error")
            self.stop_routing() # Attempt to clean up if failed to start

    def stop_routing(self):
        if self.audio_router:
            self.audio_router.stop_routing()
            # It's good practice to call shutdown here to ensure PyAudio is terminated
            self.audio_router.shutdown() 
            self.audio_router = None
        self.status_label.config(text="Status: Stopped")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def on_closing(self):
        if self.audio_router:
            self.audio_router.shutdown() # Call shutdown on close
        self.master.destroy()

if __name__ == "__main__":
    # Ensure all three parts (list_audio_devices, AudioRouter, AudioSplitterApp)
    # are in the same script or correctly imported.
    # The AudioRouter class must have the changes mentioned in the previous answer
    # (i.e., not re-routing to the primary_output_stream).

    root = tk.Tk()
    app = AudioSplitterApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
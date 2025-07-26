import tkinter as tk
from tkinter import ttk, messagebox
import threading
import pyaudiowpatch as pyaudio
import numpy as np
import threading
import time

# Helper function to get supported rates
def get_supported_rates(p, device_index, io='output'):
    """Tests common sample rates for a given device."""
    info = p.get_device_info_by_index(device_index)
    supported_rates = []
    common_rates = [44100, 48000, 96000, 88200, 192000]

    for rate in common_rates:
        try:
            format = pyaudio.paInt16
            channels = 1 # Start with mono to maximize compatibility for testing
            if io == 'output' and info['maxOutputChannels'] >= 2:
                channels = 2
            elif io == 'input' and info['maxInputChannels'] >= 2:
                channels = 2

            if io == 'output':
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
            pass
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
        self.common_sample_rate = int(self.loopback_info['defaultSampleRate'])
        self.common_channels = self.loopback_info['maxInputChannels'] # Loopback maxInputChannels is its output channels
        self.common_format = pyaudio.paInt16 # Using 16-bit integer format

        # Add a check that the secondary device actually supports this rate and channels
        secondary_supported_rates = get_supported_rates(self.p, self.secondary_device_index, 'output')
        
        if self.common_sample_rate not in secondary_supported_rates:
            print(f"WARNING: Secondary device '{self.secondary_info['name']}' does not directly support the primary loopback sample rate ({self.common_sample_rate} Hz).")
            # Fallback: find a common rate
            fallback_rates = [48000, 44100] # Prioritize 48kHz, then 44.1kHz
            found_fallback = False
            for rate in fallback_rates:
                if rate in secondary_supported_rates and self.p.is_format_supported(
                    self.common_sample_rate, # The rate used for the loopback
                    self.common_channels,   # The channels used for the loopback
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
             # Severe Issue
             print(f"WARNING: Secondary device '{self.secondary_info['name']}' only supports {self.secondary_info['maxOutputChannels']} output channels, but primary loopback provides {self.common_channels}. Attempting to use primary channels.")
             # Might need to add logic to downmix if channels mismatch
             # self.common_channels = min(self.common_channels, self.secondary_info['maxOutputChannels'])

        print(f"Audio parameters chosen: Rate={self.common_sample_rate} Hz, Channels={self.common_channels}, Format={self.common_format}")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        audio_data = np.frombuffer(in_data, dtype=np.int16) 

        # for setting secondary output stream
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
            # block to control primary output stream, in case not activily playing
            # self.primary_output_stream = self.p.open(
            #     format=self.common_format,
            #     channels=self.common_channels,
            #     rate=self.common_sample_rate,
            #     output=True,
            #     output_device_index=self.primary_device_index,
            #     frames_per_buffer=1024
            # )
            # print(f"Opened primary output stream on {self.primary_info['name']}")

            # Open the secondary output stream
            self.secondary_output_stream = self.p.open(
                format=self.common_format,
                channels=self.common_channels,
                rate=self.common_sample_rate,
                output=True,
                output_device_index=self.secondary_device_index,
                frames_per_buffer=1024
            )
            print(f"Opened secondary output stream on {self.secondary_info['name']}")

            # Open the loopback input stream
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


def list_audio_devices():
    p = None
    devices = []
    seen_device_keys = set() 

    # Exclude devices that are logical pointers or aliases used by Windows
    EXCLUDE_DEVICE_NAMES = [
        'Microsoft Sound Mapper - Input',
        'Microsoft Sound Mapper - Output',
        'Primary Sound Capture Driver',
        'Primary Sound Driver'
    ]

    try:
        p = pyaudio.PyAudio()

        wasapi_host_api_index = None
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            wasapi_host_api_index = wasapi_info['index']
        except OSError as e:
            wasapi_host_api_index = None

        total_pyaudio_devices = p.get_device_count()

        # Iterate through all global PyAudio device indices
        for i in range(total_pyaudio_devices):
            try:
                info = p.get_device_info_by_index(i) # Get info using the global index

                device_name = info['name']
                device_index = info['index'] # This is the global PyAudio index

                if device_name in EXCLUDE_DEVICE_NAMES:
                    continue

                max_output_channels = info.get('maxOutputChannels', 0)
                max_input_channels = info.get('maxInputChannels', 0)

                # Create a unique key for deduplication.
                device_key = None
                if max_output_channels > 0: 
                    device_key = (device_name, max_output_channels, 'output')
                elif max_input_channels > 0: 
                    device_key = (device_name, max_input_channels, 'input')
                else:
                    continue

                if device_key in seen_device_keys:
                    continue
                
                seen_device_keys.add(device_key) # Add the new unique key

                device_is_loopback = info.get('isLoopbackDevice', False) 
                
                # Also check common naming convention for WASAPI loopback
                if wasapi_host_api_index is not None and info['hostApi'] == wasapi_host_api_index:
                    if '[Loopback]' in device_name:
                        device_is_loopback = True

                # If device has channels and is not a duplicate, add it
                devices.append({
                    'name': device_name,
                    'index': device_index,
                    'is_loopback': device_is_loopback,
                    'maxOutputChannels': max_output_channels,
                    'maxInputChannels': max_input_channels
                })

            except Exception as e:
                import traceback # Import traceback here to keep it localized to this error handler
                traceback.print_exc()
                continue 

    except Exception as e:
        import traceback
        traceback.print_exc()
        return []

    finally:
        if p:
            p.terminate()

    return devices


class TwinPlay:
    def __init__(self, master):
        self.master = master
        master.title("TwinPlay")

        self.audio_router = None
        self.devices = list_audio_devices() # Call the helper function to get device list

        self.primary_device_var = tk.StringVar(master)
        self.secondary_device_var = tk.StringVar(master)

        self.setup_gui()

    def setup_gui(self):
        # Primary Device Selection
        ttk.Label(self.master, text="Audio Source Device:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.primary_device_dropdown = ttk.Combobox(self.master, textvariable=self.primary_device_var, state="readonly")
        self.primary_device_dropdown['values'] = [d['name'] for d in self.devices if not d['is_loopback'] and d['maxOutputChannels'] > 0]
        self.primary_device_dropdown.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.primary_device_dropdown.bind("<<ComboboxSelected>>", self.on_primary_device_selected)

        # Secondary Device Selection
        ttk.Label(self.master, text="Secondary Output Device:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
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

        # Initial device selection
        if len(self.devices) > 0:
            # Pre-select the default output device as the primary source
            default_output_device_name = self.get_default_output_device_name()
            if default_output_device_name:
                self.primary_device_var.set(default_output_device_name)
                self.on_primary_device_selected(None) # Manually call handler

            # Pre-select a different device for secondary if available
            available_for_secondary = [d['name'] for d in self.devices if not d['is_loopback'] and d['name'] != self.primary_device_var.get() and d['maxOutputChannels'] > 0]
            if available_for_secondary:
                # Pick a Bluetooth device if available and not the primary
                bluetooth_device = next((name for name in available_for_secondary if "bluetooth" in name.lower()), None)
                if bluetooth_device:
                    self.secondary_device_var.set(bluetooth_device)
                else:
                    self.secondary_device_var.set(available_for_secondary[0])
                self.on_secondary_device_selected(None)

    def get_default_output_device_name(self):
        """Helper to find the currently set default output device name."""
        try:
            # Create a *new* PyAudio instance here
            p = pyaudio.PyAudio()
            
            default_output_info = p.get_default_output_device_info()
            default_output_index = default_output_info['index']
            p.terminate() # Always terminate PyAudio instance created in a helper

            print(f"PyAudio default output device index: {default_output_index}")
            default_device = next((d for d in self.devices if d['index'] == default_output_index), None)
            
            if default_device:
                print(f"Found default device: {default_device['name']}")
                return default_device['name']
            else:
                print(f"Default output device (index {default_output_index}) not found in our gathered device list.")
                return None

        except Exception as e:
            print(f"Could not get default output device name via pyaudio: {e}")
            return None


    def on_primary_device_selected(self, event):
        selected_name = self.primary_device_var.get()
        # Allow primary and secondary to be the same initially, but the logic in AudioRouter will prevent feedback
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
            # call shutdown to ensure PyAudio is terminated
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
    root = tk.Tk()
    app = TwinPlay(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

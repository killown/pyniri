pyniri
======

Python 3.13+ License: GPL-3.0 Linux

**pyniri** is a robust, Pythonic IPC library for interacting with the [niri scroll-tiling compositor](https://github.com/YaLTeR/niri). It provides a strictly typed interface to send requests and execute actions directly through the Unix socket.

Installation
------------

Ensure you have Python 3.13 or newer installed.

    git clone https://github.com/killown/pyniri.git
    cd pyniri
    pip install .

Usage
-----

Connect to the running niri instance automatically using the `NIRI_SOCKET` environment variable.

### 1\. Basic Connection & Introspection

    from pyniri import NiriSocket, NiriError
    
    try:
        niri = NiriSocket()
        print(f"Connected to Niri v{niri.get_version()}")
    
        # List open windows
        windows = niri.get_windows()
        for win in windows:
            print(f"ID: {win['id']} | Title: {win.get('title', 'Unknown')}")
    
    except NiriError as e:
        print(f"Error: {e}")

### 2\. Controlling Windows

    from pyniri import NiriSocket
    
    niri = NiriSocket()
    
    # Close a specific window by ID
    niri.close_window(id=123)
    
    # Focus a window in a specific column index
    niri.focus_window_in_column(index=1)
    
    # Move the currently focused window to a workspace
    from pyniri.ipc import WorkspaceReference
    niri.move_window_to_workspace(WorkspaceReference.name("Browser"))

### 3\. Using Helper Classes

`pyniri` includes helper classes to generate complex JSON arguments for resizing, moving, and output configuration.

    from pyniri.ipc import SizeChange, OutputAction
    
    # Resize window: Set width to 800px fixed
    niri.set_window_width(SizeChange.set_fixed(800))
    
    # Configure Monitor: Set 1920x1080 @ 60Hz and Rotate 90 degrees
    custom_mode = OutputAction.mode(1920, 1080, 60.0)
    niri.configure_output("eDP-1", custom_mode)
    
    niri.configure_output("eDP-1", OutputAction.transform("90"))


### **License:** GPL-3.0-or-later

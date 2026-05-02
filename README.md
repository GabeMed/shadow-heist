# Shadow Heist - The Game


**Engine:** Panda3D 1.10+ / Python 3.10+  

## Quick start
py -3.11 -m venv venv
.\venv\Scripts\activate
pip install panda3d

## What works
- `Guard` walks a closed waypoint loop with configurable wait times.
- Heading smoothly rotates to face direction of travel.
- HUD displays guard state, position, and current target waypoint.

## Running the test
python main_ai_test.py
You should see a dark scene with three red waypoint pillars. The green guard card walks between them, pausing at each, and the HUD in the top-left tracks its position and state in real time. Press Escape to quit.
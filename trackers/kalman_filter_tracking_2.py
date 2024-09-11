# -*- coding: utf-8 -*-
"""Kalman_filter_tracking.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1l9RFsI9qVdL0loR3WH1h4x7ax9TeAClw
"""
import os

import pandas as pd
from numpy.linalg import inv
import numpy as np
import math
import cv2
import torch
from matplotlib import pyplot as plt

import torch
from ultralytics import YOLO

SINGLES_WIDTH = 5.18
DOUBLES_WIDTH = 6.1
VERTICAL_LENGTH = 13.4


model = YOLO('models/shuttle_detection/weights/best.pt')

# Ensure to use the GPU if available
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)

def draw_prediction(img: np.ndarray,
                    class_name: str,
                    df: pd.core.series.Series,
                    color: tuple = (255, 0, 0)):
    '''
    Function to draw prediction around the bounding box identified by the YOLO
    The Function also displays the confidence score top of the bounding box
    '''

    cv2.rectangle(img, (int(df.xmin), int(df.ymin)),
                  (int(df.xmax), int(df.ymax)), color, 2)
    cv2.putText(img, class_name + " " + str(round(df.confidence, 2)),
                (int(df.xmin) - 10, int(df.ymin) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    return img

class KalmanFilter():
    def __init__(self,
                 xinit: int = 0,
                 yinit: int = 0,
                 fps: int = 30,
                 std_a: float = 0.001,
                 std_x: float = 0.0045,
                 std_y: float = 0.01,
                 cov: float = 100000) -> None:

        # State Matrix
        self.S = np.array([xinit, 0, 0, yinit, 0, 0])
        self.dt = 1 / fps

        # State Transition Model
        # Here, we assume that the model follow Newtonian Kinematics
        self.F = np.array([[1, self.dt, 0.5 * (self.dt * self.dt), 0, 0, 0],
                           [0, 1, self.dt, 0, 0, 0], [0, 0, 1, 0, 0, 0],
                           [0, 0, 0, 1, self.dt, 0.5 * self.dt * self.dt],
                           [0, 0, 0, 0, 1, self.dt], [0, 0, 0, 0, 0, 1]])

        self.std_a = std_a

        # Process Noise
        self.Q = np.array([
            [
                0.25 * self.dt * self.dt * self.dt * self.dt, 0.5 * self.dt *
                self.dt * self.dt, 0.5 * self.dt * self.dt, 0, 0, 0
            ],
            [
                0.5 * self.dt * self.dt * self.dt, self.dt * self.dt, self.dt,
                0, 0, 0
            ], [0.5 * self.dt * self.dt, self.dt, 1, 0, 0, 0],
            [
                0, 0, 0, 0.25 * self.dt * self.dt * self.dt * self.dt,
                0.5 * self.dt * self.dt * self.dt, 0.5 * self.dt * self.dt
            ],
            [
                0, 0, 0, 0.5 * self.dt * self.dt * self.dt, self.dt * self.dt,
                self.dt
            ], [0, 0, 0, 0.5 * self.dt * self.dt, self.dt, 1]
        ]) * self.std_a * self.std_a

        self.std_x = std_x
        self.std_y = std_y

        # Measurement Noise
        self.R = np.array([[self.std_x * self.std_x, 0],
                           [0, self.std_y * self.std_y]])

        self.cov = cov

        # Estimate Uncertainity
        self.P = np.array([[self.cov, 0, 0, 0, 0, 0],
                           [0, self.cov, 0, 0, 0, 0],
                           [0, 0, self.cov, 0, 0, 0],
                           [0, 0, 0, self.cov, 0, 0],
                           [0, 0, 0, 0, self.cov, 0],
                           [0, 0, 0, 0, 0, self.cov]])

        # Observation Matrix
        # Here, we are observing X & Y (0th index and 3rd Index)
        self.H = np.array([[1, 0, 0, 0, 0, 0], [0, 0, 0, 1, 0, 0]])

        self.I = np.array([[1, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0],
                           [0, 0, 1, 0, 0, 0], [0, 0, 0, 1, 0, 0],
                           [0, 0, 0, 0, 1, 0], [0, 0, 0, 0, 0, 1]])

        # Predicting the next state and estimate uncertainity
        self.S_pred = None
        self.P_pred = None

        # Kalman Gain
        self.K = None

        # Storing all the State, Kalman Gain and Estimate Uncertainity
        self.S_hist = [self.S]
        self.K_hist = []
        self.P_hist = [self.P]

    def pred_new_state(self):
        self.S_pred = self.F.dot(self.S)

    def pred_next_uncertainity(self):
        self.P_pred = self.F.dot(self.P).dot(self.F.T) + self.Q

    def get_Kalman_gain(self):
        self.K = self.P_pred.dot(self.H.T).dot(
            inv(self.H.dot(self.P_pred).dot(self.H.T) + self.R))
        self.K_hist.append(self.K)

    def state_correction(self, z):
        if z == [None, None]:
            self.S = self.S_pred
        else:
            self.S = self.S_pred + +self.K.dot(z - self.H.dot(self.S_pred))

        self.S_hist.append(self.S)

    def uncertainity_correction(self, z):
        if z != [None, None]:
            self.l1 = self.I - self.K.dot(self.H)
            self.P = self.l1.dot(self.P_pred).dot(self.l1.T) + self.K.dot(
                self.R).dot(self.K.T)
        self.P_hist.append(self.P)

def cost_fun(a, b):
    '''
    Cost function for filter Assignment
    Uses euclidean distance for choosing the filter
    '''

    sm = 0
    for i in range(len(a)):
        sm += (a[i] - b[i])**2
    return sm

import json
import numpy as np
import cv2
from collections import Counter

def identify_stationary_objects(threshold=10):
    """
    Identifies stationary objects by grouping similar coordinates based on frequency of occurrence
    and merging those that are close together.
    """
    global global_coord_frequency, stationary_coords

    # Get the list of coordinates and their frequencies from the global frequency dictionary
    coords_with_freq = list(global_coord_frequency.items())

    def group_coordinates_by_proximity(coords_with_freq, threshold):
        """
        Groups coordinates in the global frequency dictionary by proximity and sums their frequencies.
        """
        grouped_freq = []
        used = [False] * len(coords_with_freq)

        for i in range(len(coords_with_freq)):
            if used[i]:
                continue

            current_group = [coords_with_freq[i][0]]  # Start a new group with the current coordinate
            total_freq = coords_with_freq[i][1]  # Initialize total frequency with current frequency
            used[i] = True

            for j in range(i + 1, len(coords_with_freq)):
                # Compute the Euclidean distance between the coordinates
                dist = np.linalg.norm(np.array(coords_with_freq[i][0]) - np.array(coords_with_freq[j][0]))
                if dist < threshold:
                    current_group.append(coords_with_freq[j][0])
                    total_freq += coords_with_freq[j][1]
                    used[j] = True

            # Average the grouped coordinates
            avg_coord = tuple(np.mean(current_group, axis=0))
            grouped_freq.append((avg_coord, total_freq))

        return grouped_freq

    # Group the coordinates by proximity
    grouped_coords_with_freq = group_coordinates_by_proximity(coords_with_freq, threshold)

    # Define a threshold for considering an object stationary based on frequency
    stationary_threshold = 10  # You can adjust this value

    # Find coordinates that occur above the threshold and add to stationary_coords
    stationary_coords = [(coord,freq) for coord, freq in grouped_coords_with_freq if freq > stationary_threshold]

    return stationary_coords

def group_similar_coordinates(coords, threshold=10):
    """
    Groups coordinates that are within a threshold distance from each other.
    Returns a list of unique coordinates (averaged within the group).
    Also updates the global frequency dictionary.
    """
    grouped_coords = []
    used = [False] * len(coords)

    for i in range(len(coords)):
        if used[i]:
            continue

        # Start a new group with the current coordinate
        current_group = [coords[i]]
        used[i] = True

        for j in range(i + 1, len(coords)):
            # Compute the Euclidean distance between coordinates
            dist = np.linalg.norm(np.array(coords[i]) - np.array(coords[j]))
            if dist < threshold:
                current_group.append(coords[j])
                used[j] = True

        # Average the grouped coordinates
        avg_coord = tuple(np.mean(current_group, axis=0))
        grouped_coords.append((avg_coord, len(current_group)))

        # Update global coordinate frequency
        if avg_coord in global_coord_frequency:
            global_coord_frequency[avg_coord] += len(current_group)
        else:
            global_coord_frequency[avg_coord] = len(current_group)

    return grouped_coords


def is_close_to_blacklist(coord, black_list, threshold=1):
    for black_coord in black_list:
        distance = np.sqrt((coord[0] - black_coord[0])**2 + (coord[1] - black_coord[1])**2)
        if distance <= threshold:
            return True
    return False

import cv2
import json
import pandas as pd
from collections import deque, Counter
import numpy as np

number_of_past_frames = 5
def is_shuttle_in_rest(shuttle_coords_queue, number_of_past_frames, threshold=5):

    if len(shuttle_coords_queue) < number_of_past_frames:
        return False  # Not enough data to determine movement

    # Get the minimum and maximum x and y coordinates from the last 20 frames
    x_coords = [coord[0] for coord in shuttle_coords_queue]
    y_coords = [coord[1] for coord in shuttle_coords_queue]

    # Check if the difference between max and min is within the threshold
    if max(x_coords) - min(x_coords) <= threshold and max(y_coords) - min(y_coords) <= threshold:
        return True  # Shuttle is at rest
    else:
        return False  # Shuttle is moving
# print(os.getcwd())
with open('result/court_and_net/courts/court_kp/coordinates.json', 'r') as f:
    data = json.load(f)

court_coords = data["court_info"]
net_coords = data["net_info"]

# print(f"court_coords = {court_coords},")
# print(f"net_coords = {net_coords},")
def is_shuttle_in_court(shuttle_coord, court_coords, net_coords):
    """Check if the shuttle is inside the court using cv2.pointPolygonTest."""
    # Convert court coordinates to a numpy array of shape (n, 1, 2) required by cv2
    # Court-1 (towards camera)
    court1 = court_coords[2:]
    court_polygon = np.array(court1, dtype=np.int32).reshape((-1, 1, 2))
    # Check if the point is inside the polygon
    result1 = cv2.pointPolygonTest(court_polygon, shuttle_coord, False)

    # Court-2 (away from camera)
    court2 = court_coords[:4]
    court_polygon = np.array(court2, dtype=np.int32).reshape((-1, 1, 2))
    # Check if the point is inside the polygon
    result2 = cv2.pointPolygonTest(court_polygon, shuttle_coord, False)

    '''
    1: shuttle in court near camera
    2: shuttle in court away from camera
    False: outside
    '''
    if result1 >= 0:
        return 1  # Shuttle is inside or on the court
    if result2 >= 0:
        return 2
    return False  # Shuttle is outside the court

def determine_shooter(shuttle_coords_deque):
    """Determine which player shot the shuttle using the deque of shuttle coordinates.

    Args:
        shuttle_coords_deque: A deque containing the shuttle coordinates (x, y) for the last 20 frames.

    Returns:
        1: If the shuttle was shot by player 1 (moving downward).
        2: If the shuttle was shot by player 2 (moving upward).
        None: If there's not enough information.
    """
    if len(shuttle_coords_deque) < 2:
        return 0  # Not enough data to determine the shooter

    # Extract y-coordinates from the deque
    y_coords = [coord[1] for coord in shuttle_coords_deque]

    # Calculate the difference between consecutive y-coordinates
    deltas = np.diff(y_coords)  # This will give us the differences between frames

    # Analyze the y-coordinate differences to determine the direction of motion
    avg_delta = np.mean(deltas)  # Get the average direction of movement

    # If avg_delta > 0, shuttle is moving downward (toward player 1), player 2 shot it
    # If avg_delta < 0, shuttle is moving upward (toward player 2), player 1 shot it
    if avg_delta > 0:
        return 2  # Player 2 shot the shuttle (moving toward player 1)
    elif avg_delta < 0:
        return 1  # Player 1 shot the shuttle (moving toward player 2)

    return 0  # No clear direction

def assign_points(shuttle_position, prev_k_frame):
    if shuttle_position == 1:
        score[1] += 1

    elif shuttle_position == 2:
        score[0] += 1

    else:
        shooter = determine_shooter(prev_k_frame)
        if shooter == 2:
            score[0] += 1
        else:
            score[1] += 1

def check_shuttle_in_net_rectangle(rest_coord, net_start, net_end, above=30, below=50):
    """
    Checks if the shuttle came to rest by touching the net and falling.

    Parameters:
    rest_coord: Tuple (x, y) - The final rest coordinate of the shuttle.
    net_start: Tuple (x, y) - The start coordinate of the net (court_coords[2]).
    net_end: Tuple (x, y) - The end coordinate of the net (court_coords[3]).
    above: int - Distance above the net line in pixels (default is 30 pixels).
    below: int - Distance below the net line in pixels (default is 50 pixels).

    Returns:
    bool - True if the shuttle touched the net and fell, False otherwise.
    """

    # Calculate the midpoint of the net line
    net_start = np.array(net_start)
    net_end = np.array(net_end)
    
    net_length = np.linalg.norm(net_end - net_start)
    
    if net_length == 0:
        raise ValueError("Net length is zero. Invalid net coordinates.")

    # Calculate the unit direction vector of the net line
    net_direction = (net_end - net_start) / net_length

    # Define the vertical extension range (30 above and 50 below the net line)
    rectangle_top = net_start[1] - above
    rectangle_bottom = net_start[1] + below

    # Define left and right edges (x coordinates are the same as net_start and net_end)
    left_x = min(net_start[0], net_end[0])
    right_x = max(net_start[0], net_end[0])

    # Check if the shuttle is within the bounds of this rectangle
    shuttle_x, shuttle_y = rest_coord

    if left_x <= shuttle_x <= right_x and rectangle_top <= shuttle_y <= rectangle_bottom:
        return True  # Shuttle touched the net and fell
    else:
        return False  # Shuttle did not touch the net or fell outside


import cv2
import numpy as np
import pandas as pd
import json
from collections import Counter, deque
from scipy.ndimage import uniform_filter1d
# Initialize the global coordinate frequency dictionary
global_coord_frequency = {}
stationary_coords = []
score=[0,0]
relay_flag=0
relay_start_frame = None  # Track the frame where the relay starts

def is_consistently_decreasing(y_coords, window_size=5):
    """
    Check if y-coordinates are consistently decreasing over a window of frames.
    """
    # print(y_coords)
    if len(y_coords) < window_size:
        return False
    recent_coords = list(y_coords)[-window_size:]

    return all(recent_coords[i] > recent_coords[i+1] for i in range(window_size-1))

def is_consistently_increasing(y_coords, window_size=5):
    """
    Check if y-coordinates are consistently decreasing over a window of frames.
    """
    # print(y_coords)
    if len(y_coords) < window_size:
        return False
    recent_coords = list(y_coords)[-window_size:]

    return all(recent_coords[i] < recent_coords[i+1] for i in range(window_size-1))
def calculate_speed(coord, lastx, lasty, lastframeno, frame_count, fps):
    if lastx is None:
        return 0
    
    # Ensure all values are float
    coord = [float(coord[0]), float(coord[1])]
    lastx, lasty = float(lastx), float(lasty)
    
    # Calculate court scaling factors
    width_scale = SINGLES_WIDTH / (court_coords[5][0] - court_coords[0][0])
    height_scale = VERTICAL_LENGTH / (court_coords[5][1] - court_coords[0][1])
    
    # Calculate distance
    dx = (coord[0] - lastx) * width_scale
    dy = (coord[1] - lasty) * height_scale
    distance = np.sqrt(dx**2 + dy**2)
    
    # Calculate time difference
    time_diff = (frame_count - lastframeno) / fps
    
    # Calculate speed
    speed = distance / time_diff if time_diff > 0 else 0
    
    return speed

#

def real_time_detection_and_tracking(frames, fps, find_black_list, black_list):
    global global_coord_frequency, stationary_coords, relay_flag, relay_start_frame, score
    print(f"function call: {score}")
    print(f"FPS: {fps}")

    # Initialize Kalman filter (assuming one object for now)
    # filter_multi = [KalmanFilter(fps=fps, xinit=60, yinit=150, std_x=0.000025, std_y=0.0001)]

    # Set up the video writer for saving the result
    frame_height, frame_width = frames[0].shape[:2]
    out = cv2.VideoWriter('garbage/realtime_tracking_kalman.mp4', cv2.VideoWriter_fourcc(*'mp4v'), fps, (frame_width, frame_height))

    tracking_data = {}
    scored = False
    coord_counter = Counter()
    frame_count = 0
    shuttle_coords_queue = deque(maxlen=10)
    prev_k_frame = deque(maxlen=10)
    black_list = black_list
    # black_list = [(1894.7992769129137, 303.175568075741), (2333.0154160860784, 1482.0646242436044), (1008.7924158432904, 313.01178965849033)]
    lastx, lasty, lastframeno = None, None, None

    listt = {}
    speed_history = []
    rest_coords = []
    y_coord_history = deque(maxlen=10)
    # Rest state tracking
    rest_state_counter = 0
    REST_THRESHOLD = 3  # Number of consecutive frames to consider as "at rest"

    points = {}
    net_ke_pas = False
    for frame in frames:
        if scored and relay_flag:
            scored = False

        print(f"Processing frame {frame_count}")

        results = model([frame])

        boxes = results[0].boxes.xyxy.cpu().numpy()
        class_ids = results[0].boxes.cls.cpu().int().numpy()
        scores = results[0].boxes.conf.cpu().numpy()

        df_current = pd.DataFrame({
            'xmin': boxes[:, 0],
            'ymin': boxes[:, 1],
            'xmax': boxes[:, 2],
            'ymax': boxes[:, 3],
            'class_id': class_ids,
            'confidence': scores
        })

        current_coords = []
        if frame_count not in listt:
            listt[frame_count] = []

        for _, row in df_current.iterrows():
            coord = [(row['xmin'] + row['xmax']) / 2, (row['ymin'] + row['ymax']) / 2]

            if row['class_id'] == 0:
                if not is_close_to_blacklist(coord, black_list, threshold=15):
                    current_coords.append(coord)
                    
                    speed = calculate_speed(coord, lastx, lasty, lastframeno, frame_count, fps)
                    listt[frame_count].append({
                        'x_center': coord[0],
                        'y_center': coord[1],
                        'speed': speed
                    })

                    lastx, lasty, lastframeno = coord[0], coord[1], frame_count

        # Update tracking_data and check for rest state
        is_at_rest = False
        if frame_count in listt and len(listt[frame_count]) == 1:
            coord = (listt[frame_count][0]['x_center'], listt[frame_count][0]['y_center'])
            shuttle_coords_queue.append(coord)
            prev_k_frame.append(coord)
            y_coord_history.append(coord[1])

            # Relay start detection
            if relay_flag == 0 and determine_shooter(prev_k_frame.copy())==1 and is_consistently_decreasing(y_coord_history):
                relay_flag = 1
                relay_start_frame = frame_count  # Track when the relay starts
                # print(f"Relay start at frame {frame_count}")
            elif relay_flag==0 and determine_shooter(prev_k_frame.copy())==2 and is_consistently_increasing(y_coord_history):
                relay_flag = 1
                relay_start_frame = frame_count  # Track when the relay starts
                # print(f"Relay start at frame {frame_count}")
            # print(f"shuttle_coords_queue: {shuttle_coords_queue}")
            if is_shuttle_in_rest(shuttle_coords_queue, 10):
                rest_state_counter += 1
                if rest_state_counter >= REST_THRESHOLD:
                    is_at_rest = True
                    rest_coords.append(coord)
                if is_at_rest and relay_flag == 1:
                    relay_flag = 0
                    relay_start_frame = None  # Reset relay start frame

            else:
                rest_state_counter = 0

            speed_history.append(listt[frame_count][0]['speed'])
            if len(speed_history) > 5:
                speed_history.pop(0)
            smoothed_speed = np.mean(speed_history)

            tracking_data[f"{frame_count}"] = {
              'x_center': coord[0],
              'y_center': coord[1],
              'smoothened_speed': smoothed_speed,
              'is_at_rest': is_at_rest,
              'relay_active': relay_flag == 1,
            }
        else:
            tracking_data[f"{frame_count}"] = {
                'x_center': None,
                'y_center': None,
                'smoothened_speed': None,
                'is_at_rest': None,
                'relay_active': None,
            }

        grouped_coords = group_similar_coordinates(current_coords, threshold=10)
        rest_coords = group_similar_coordinates(rest_coords, threshold=10)
        if rest_coords:
            rest_coords = [rest_coords[0][0]]

        coord_counter.clear()
        for coord, count in current_coords:
            coord_counter[coord] += count

        # Visualization

        dummy = 15

        # for x, y in current_coords:
        #     cv2.rectangle(frame, (int(x) - dummy, int(y) - dummy),
        #                   (int(x) + dummy, int(y) + dummy), (0, 255, 0), 2)
        #
        #     if str(frame_count) in tracking_data:
        #         font = cv2.FONT_HERSHEY_SIMPLEX
        #         speed = tracking_data[str(frame_count)]['smoothened_speed']
        #         speed_text = f"Speed: {speed:.2f}"
        #         cv2.putText(frame, speed_text, (int(x) - dummy, int(y) - dummy - 10),
        #                     font, 0.5, (0, 140, 255), 2)

        # Draw black list rectangles
        for x, y in black_list:
            cv2.rectangle(frame, (int(x) - dummy, int(y) - dummy),
                          (int(x) + dummy, int(y) + dummy), (0, 140, 255), 5)
            cv2.putText(frame, 'stationary', (int(x) - dummy, int(y) - dummy - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 140, 255), 2)

        # Draw rest state indicator
        
        if is_at_rest:
            coordabs = rest_coords[-1]
            coordabs = (float(coordabs[0]), float(coordabs[1]))
            if not scored:
              shuttle_position = is_shuttle_in_court(coordabs, court_coords, net_coords)
              print(f"Score before assigning: {score}")
              assign_points(shuttle_position, prev_k_frame.copy())
              print(f"Score after assigning: {score}")
              scored = True
            last_rest_coord = rest_coords[-1]
            text_position = (int(last_rest_coord[0]), int(last_rest_coord[1]) - 30)
            cv2.putText(frame, f'Shuttle is at rest: {shuttle_position}', text_position, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
            cv2.putText(frame, f'Shuttle is at rest: {shuttle_position}', text_position, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            if check_shuttle_in_net_rectangle(coordabs, court_coords[2], court_coords[3], above=30, below=50):
                net_ke_pas = True
                net_frame = frame_count
                
        if net_ke_pas:
            text_position = (text_position[0], text_position[1] + 90)
            cv2.putText(frame, 'Shuttle hit the net net net net net', text_position, cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2)
            if frame_count >= (net_frame + 20):
                net_ke_pas = False
        
        # Calculate relay time
        if relay_flag == 1 and relay_start_frame is not None:
            relay_duration = frame_count - relay_start_frame
            relay_text = f"Relay Time: {relay_duration} frames"
        else:
            relay_text = "Relay Inactive"

        cv2.putText(frame, relay_text, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Position for score[1] (Player 2's score) at the top-left corner
        top_left_position = (50, 50)  # (x, y) coordinates for top-left corner

        # Position for score[0] (Player 1's score) at the bottom-left corner
        bottom_left_position = (50, frame_height - 50)  # (x, y) coordinates for bottom-left corner

        # Draw Player 2's score (top-left)
        cv2.putText(frame, f"Player 2: {score[1]}", top_left_position, cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)

        # Draw Player 1's score (bottom-left)
        cv2.putText(frame, f"Player 1: {score[0]}", bottom_left_position, cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 5)

        points[f"{frame_count}"] = {
            'Player 1': score[0],
            'Player 2': score[1]
        }

        # prev_k_frame.append(coord)
        frame_count += 1

    with open('result/scoring/score.json', 'w') as json_file:
        json.dump(points, json_file, indent=4)

    with open('result/shuttle_data/shuttle_data.json', 'w') as json_file:
        json.dump(tracking_data, json_file, indent=4)
        
    score = [0,0]
    if find_black_list:
        stationary_coords = identify_stationary_objects()
        # print("Stationary coordinates detected:")
        # print(stationary_coords)
        final = []
        for cod, freq in stationary_coords:
            final.append(cod)
        
        print(f"black_listed points: {final}")
        global_coord_frequency = {}
        stationary_coords = []
        return final
    
    global_coord_frequency = {}
    stationary_coords = []
    return frames, tracking_data

def draw_shuttle_predictions(frames, tracking_data):
    output_frames = []
    i = 0
    for frame in frames:
        output_frame = draw_shuttle_predictions_frame(frame, tracking_data, i)
        i = i + 1

        output_frames.append(output_frame)

    return output_frames


def draw_shuttle_predictions_frame(frame, tracking_data, i):
    dummy = 15

    if i in tracking_data:
        x = tracking_data[i]['x_center']
        y = tracking_data[i]['y_center']
        if np.isnan(x) or np.isnan(y):
            return frame  
        speed = tracking_data[i]['smoothened_speed']

        # print("lol")
        # print(x, y)
        cv2.rectangle(frame, (int(x) - dummy, int(y) - dummy),
                      (int(x) + dummy, int(y) + dummy), (0, 255, 0), 2)

        speed_text = f"Speed: {speed:.2f}"
        cv2.putText(frame, speed_text, (int(x) - dummy, int(y) - dummy - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 140, 255), 3)

    return frame

def interpolate_shuttle_tracking(tracking_data):
    # with open(json_path, 'r') as file:
    #     tracking_data = json.load(file)

    # Extract the x and y coordinates for each frame from the JSON data
    shuttle_coordinates_frames = [
        (frame_data['x_center'], frame_data['y_center'], frame_data['smoothened_speed'])
        for frame_data in tracking_data.values()
    ]

    # Convert the coordinates into a pandas DataFrame
    df_shuttle_positions = pd.DataFrame(shuttle_coordinates_frames, columns=['x_center', 'y_center', 'smoothened_speed'])

    # Convert columns to numeric type
    for col in df_shuttle_positions.columns:
        df_shuttle_positions[col] = pd.to_numeric(df_shuttle_positions[col], errors='coerce')

    # Interpolate missing values
    df_shuttle_positions = df_shuttle_positions.interpolate(method='linear')

    # Fill any remaining NaN values (at the start or end) with the nearest valid value
    df_shuttle_positions = df_shuttle_positions.bfill().ffill()

    # Convert the DataFrame back to a dictionary
    tracking_data = df_shuttle_positions.to_dict(orient='index')

    # Save the interpolated data to a JSON file
    with open('result/shuttle_data/shuttle_data.json', 'w') as json_file:
        json.dump(tracking_data, json_file, indent=4)

    return tracking_data


# Run the real-time shuttlecock detection and tracking

# real_time_detection_and_tracking('/content/drive/MyDrive/drop.mp4', 'tracking_data.json')

# prompt: save realtime_tracking_kalman.mp4 in drive using shutils. Remember shutils has no attribute copy

# import shutil

# Save the output video to Google Drive
# shutil.move('realtime_tracking_kalman.mp4', '/content/drive/My Drive/realtime_tracking_kalman.mp4')
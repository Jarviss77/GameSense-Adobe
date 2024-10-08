from utils import (read_video, write_video, read_video_few_frames)
from trackers import (
    PlayerTracker,
    ShuttleTracker,
    Doubles_Tracking,
    real_time_detection_and_tracking,
    draw_shuttle_predictions,
    interpolate_shuttle_tracking
)
from commentary import display_and_generate_commentary
import argparse
import cv2
import copy
from tqdm import tqdm
import numpy as np
import matplotlib.pyplot as plt
from torchvision.transforms import transforms
from torchvision.transforms import functional as F
import os
from models.court_and_net_detection.src.tools.utils import write_json, clear_file, is_video_detect, find_reference

from models.court_and_net_detection.src.models.CourtDetect import CourtDetect
from models.court_and_net_detection.src.models.NetDetect import NetDetect
from models.court_and_net_detection.om import draw_court_and_net_on_frames
import logging
import traceback
import warnings
import json
from speed_distance_estimator import SpeedAndDistance_Estimator


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, int):  # Handle integer types
            return str(obj)
        # Add logic for other non-standard types
        return super().default(obj)


def convert_to_number(obj):
    if isinstance(obj, dict):
        return {k: convert_to_number(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_number(item) for item in obj]
    elif isinstance(obj, str):
        try:
            return int(obj)
        except ValueError:
            try:
                return float(obj)
            except ValueError:
                return obj
    else:
        return obj


def main():
    parser = argparse.ArgumentParser(description="A script for court and player tracking")
    parser.add_argument("-doubles", action='store_true', help="doubles tracking")
    parser.add_argument("--buffer", action='store_true', help="load data from buffer rather than inferencing again")
    parser.add_argument("--video_path", type=str, required=True, help="Path to the input video")
    parser.add_argument("-speech", action='store_true', help="Display and Generate speech")
    # parser.add_argument("--nodrop_path", type=str, required=True, help="Path to the no drop video")

    args = parser.parse_args()

    read_from_record = args.buffer
    bool_doubles = args.doubles
    # input_video = args.video_path  # Get video from the user
    input_video = args.video_path
    # nodrop_video = args.nodrop_path
    bool_speech = args.speech

    # Read Video
    frames, video_fps = read_video(input_video)
    output_video = "output.mp4"

    # Court and Net Detection
    # Clear the polyfit RankWarning
    warnings.simplefilter('ignore', np.RankWarning)

    video_name = os.path.basename(input_video).split('.')[0]
    result_path = "result/court_and_net/"

    full_video_path = os.path.join(f"{result_path}/videos", video_name)
    if not os.path.exists(full_video_path):
        os.makedirs(full_video_path)

    # Open the video file
    video = cv2.VideoCapture(input_video, cv2.CAP_FFMPEG)
    # Get video properties
    fps = video.get(cv2.CAP_PROP_FPS)
    height = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
    width = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    print(height)
    print("HEYY")
    # Write video information
    video_dict = {
        "video_name": video_name,
        "fps": fps,
        "height": height,
        "width": width,
        "total_frames": total_frames
    }

    write_json(video_dict, video_name, full_video_path)

    # Initialize detection classes
    court_detect = CourtDetect()
    net_detect = NetDetect()

    reference_path = find_reference(video_name)
    if reference_path is None:
        print("There is no reference frame! Now try to find it automatically.")
    else:
        print(f"The reference frame is {reference_path}. ")

    # Read only the first frame from the video
    ret, frame = video.read()
    if not ret:
        print("Error: Could not read the first frame.")
        video.release()

    # Perform court and net detection on the first frame
    court_info, have_court = court_detect.get_court_info(frame)
    net_info, have_net = net_detect.get_net_info(frame)
    court_lines = court_detect.hori_lines_in_court(frame)

    if have_court:
        normal_court_info = court_info

        begin_frame = 0  # Since we're only processing the first frame
        next_frame = 1  # Placeholder as there's no further processing
    else:
        print("No court detected in the first frame.")
        normal_court_info = None
        begin_frame = -1
        next_frame = -1

    if have_net:
        normal_net_info = net_info
    else:
        print("No net detected in the first frame.")
        normal_net_info = None

    # Correct net position if detected
    if normal_net_info is not None and normal_court_info is not None:
        normal_net_info[1][1], normal_net_info[2][1] = \
            normal_court_info[2][1], normal_court_info[3][1]

    court_dict = {
        "first_rally_frame": begin_frame,
        "next_rally_frame": next_frame,
        "court_info": normal_court_info,
        "net_info": normal_net_info,
        "line_info": court_lines
    }
    print(court_dict)
    import json

    with open(f"{result_path}/courts/court_kp/coordinates.json", 'w') as f:
        json.dump(court_dict, f, cls=CustomJSONEncoder, indent=4)

    with open('result/court_and_net/courts/court_kp/coordinates.json', 'r') as f:
        data = json.load(f)
        data = convert_to_number(data)

    # write_json(court_dict, video_name, f"{result_path}/courts/court_kp", "w")

    # Release the video capture object after processing the first frame
    video.release()

    # Detect speed and distance
    speed_and_distance_estimation = SpeedAndDistance_Estimator()

    # Inference and Tracking
    # Players
    if bool_doubles:
        track_players = Doubles_Tracking("models/player_detection/weights/doubles/yolov8m.pt")
        detected_players = track_players.detect_frames(frames, read_from_record,
                                                       record_path="record/player_detections.pkl")
        speed_and_distance_estimation.speed_n_distance_doubles(detected_players)
    else:
        track_players = PlayerTracker("models/player_detection/weights/only_player/best.pt")
        detected_players = track_players.detect_frames(frames, read_from_record,
                                                       record_path="record/player_detections.pkl")
        speed_and_distance_estimation.speed_n_distance(detected_players)

    # Save Player Data
    track_players.save_player_data(detected_players, "result/player_data/player_data.json")

    # Draw Boxes
    # ShuttleCock
    sframes, svideo_fps = read_video_few_frames(input_video)
    black = real_time_detection_and_tracking(sframes, svideo_fps, find_black_list=1, black_list=[])

    output_frames, tracking_data = real_time_detection_and_tracking(frames, video_fps, find_black_list=0,
                                                                    black_list=black)

    # Interpolation
    tracking_data = interpolate_shuttle_tracking(tracking_data)

    output_frames = draw_shuttle_predictions(output_frames, tracking_data)

    output_frames = track_players.draw_boxes(output_frames, detected_players)

    # output_frames = track_shuttle.draw_boxes(output_frames, detected_shuttle)

    output_frames = speed_and_distance_estimation.draw_speed_and_distance(output_frames, detected_players)
    # output_frames = speed_and_distance_estimation.draw_speed_and_distance(output_frames, detected_shuttle)

    output_frames = draw_court_and_net_on_frames(output_frames)
    # output_frames = draw_shuttle_predictions(output_frames, shuttle_tracking_data, rest_coords, listt)
    write_video(output_frames, output_video, video_fps)

    # Display output video and generate commentary
    if bool_speech:
        display_and_generate_commentary(output_video, input_video, "result/player_data/player_data.json")

if __name__ == "__main__":
    main()
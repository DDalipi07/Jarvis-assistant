"""
JARVIS - Step 1: Hand gesture recognition
Shows your webcam, tracks your hand, and recognizes 5 gestures.
Press Q to quit.
"""

import time
import cv2
import mediapipe as mp

mp_hands = mp.solutions.hands
mp_draw = mp.solutions.drawing_utils

# What each gesture will do in Jarvis (just messages for now)
ACTIONS = {
    "OPEN PALM": "Pausing everything",
    "FIST": "Standby mode",
    "THUMBS UP": "Alarm snoozed",
    "PEACE": "Reading your next event",
    "POINTING": "Listening...",
}

HOLD_TIME = 1.0  # seconds you must hold a gesture before it triggers


def fingers_up(hand_landmarks, handedness):
    """Return a list of 5 True/False values: thumb, index, middle, ring, pinky."""
    lm = hand_landmarks.landmark
    fingers = []

    # Thumb: compare tip with the joint below it, sideways (depends on which hand)
    if handedness == "Right":
        fingers.append(lm[4].x < lm[3].x)
    else:
        fingers.append(lm[4].x > lm[3].x)

    # Other fingers: tip is above the middle joint = finger is up
    for tip, joint in [(8, 6), (12, 10), (16, 14), (20, 18)]:
        fingers.append(lm[tip].y < lm[joint].y)

    return fingers


def recognize(hand_landmarks, handedness):
    lm = hand_landmarks.landmark
    thumb, index, middle, ring, pinky = fingers_up(hand_landmarks, handedness)
    others = [index, middle, ring, pinky]

    if all(others) and thumb:
        return "OPEN PALM"
    if index and middle and not ring and not pinky:
        return "PEACE"
    if index and not middle and not ring and not pinky:
        return "POINTING"
    if not any(others):
        # Thumbs up: thumb tip clearly higher than the knuckles
        if lm[4].y < lm[5].y - 0.05:
            return "THUMBS UP"
        return "FIST"
    return None


def main():
    # CAP_DSHOW makes the webcam open much faster on Windows
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Could not open the webcam. Close other apps using it (Zoom, Teams, Camera) and try again.")
        return

    current = None
    since = 0.0
    last_action = ""
    last_action_time = 0.0

    print("Jarvis online. Show your hand to the camera. Press Q in the video window to quit.")

    with mp_hands.Hands(max_num_hands=1,
                        min_detection_confidence=0.7,
                        min_tracking_confidence=0.6) as hands:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Lost the webcam feed.")
                break

            frame = cv2.flip(frame, 1)  # mirror, so it feels like a mirror
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb)

            gesture = None
            if results.multi_hand_landmarks:
                hand = results.multi_hand_landmarks[0]
                handedness = results.multi_handedness[0].classification[0].label
                mp_draw.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)
                gesture = recognize(hand, handedness)

            # Only trigger after the gesture is held steady for HOLD_TIME
            now = time.time()
            if gesture != current:
                current = gesture
                since = now
            elif gesture and now - since >= HOLD_TIME:
                last_action = f"{gesture}: {ACTIONS[gesture]}"
                last_action_time = now
                print(f"[JARVIS] {last_action}")
                since = now + 2  # wait a bit before triggering again

            # On-screen display
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 50), (20, 20, 20), -1)
            cv2.putText(frame, f"Gesture: {gesture or '-'}", (15, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 220, 255), 2)
            if last_action and now - last_action_time < 2.5:
                cv2.putText(frame, last_action, (15, frame.shape[0] - 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 120), 2)

            cv2.imshow("JARVIS - press Q to quit", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break

    cap.release()
    cv2.destroyAllWindows()
    print("Jarvis offline.")


if __name__ == "__main__":
    main()

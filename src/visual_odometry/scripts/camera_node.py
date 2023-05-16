#!/usr/bin/env python

import rospy
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
import cv2

cap = cv2.VideoCapture(0)
#cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
#cap.set(cv2.CAP_PROP_FRAME_WIDTH, 720)
#cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)


if not cap.isOpened():
    rospy.loginfo("Could not open Camera")
else:
    rospy.loginfo("Camera Connected")

bridge = CvBridge()

def img_publisher():
    pub = rospy.Publisher('/camera', Image, queue_size=1)
    rospy.init_node('my_camera')
    rate = rospy.Rate(20)
    while not rospy.is_shutdown():
        ret, frame = cap.read()
        if not ret:
            break
        msg = bridge.cv2_to_imgmsg(frame, "bgr8")
        pub.publish(msg)
    cap.release()

if __name__ == "__main__":
    try:
        img_publisher()
    except rospy.ROSInterruptException:
        rospy.loginfo("Unexpected error")
        pass

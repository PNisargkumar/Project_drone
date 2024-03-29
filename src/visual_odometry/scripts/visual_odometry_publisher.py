#!/usr/bin/env python

# Import the necessary libraries and ROS message types
import rospy
import numpy as np
import cv2
import time
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from nav_msgs.msg import Odometry
from std_msgs.msg import Header

# VisualOdometry class to handle visual odometry calculations
class VisualOdometry():
    # Constructor to initialize the object with intrinsic camera matrix
    def __init__(self, intrinsic):
        # Store the intrinsic camera matrix and other matrices for projection
        self.K = intrinsic
        self.extrinsic = np.array(((1,0,0,0),(0,1,0,0),(0,0,1,0)))
        self.P = self.K @ self.extrinsic

        # Initialize ORB feature detector
        self.orb = cv2.ORB_create(3000)

        # Initialize FLANN matcher for feature matching
        FLANN_INDEX_LSH = 6
        index_params = dict(algorithm=FLANN_INDEX_LSH, table_number=6, key_size=12, multi_probe_level=1)
        search_params = dict(checks=50)
        self.flann = cv2.FlannBasedMatcher(indexParams=index_params, searchParams=search_params)
        
        # List to store world points (3D points) from triangulation
        self.world_points = []

        # Current pose matrix, starts as identity
        self.current_pose = None

    # Static method to form a transformation matrix from rotation matrix and translation vector
    @staticmethod
    def _form_transf(R, t):
        
        T = np.eye(4, dtype=np.float64)
        T[:3, :3] = R
        T[:3, 3] = t
        
        return T

    # Function to get feature matches between two images and return corresponding points
    def get_matches(self, img1, img2):
   
        # Find keypoints and descriptors with ORB
        kp1, des1 = self.orb.detectAndCompute(img1, None)
        kp2, des2 = self.orb.detectAndCompute(img2, None)

        # Find matches using FLANN matcher
        if len(kp1) > 6 and len(kp2) > 6:
            matches = self.flann.knnMatch(des1, des2, k=2)

            # Get good matches based on Lowe's ratio test
            good_matches = []
            try:
                for m, n in matches:
                    if m.distance < 0.5 * n.distance:
                        good_matches.append(m)
            except ValueError:
                pass
            
            # Get image points from good matches
            q1 = np.float32([kp1[m.queryIdx].pt for m in good_matches])
            q2 = np.float32([kp2[m.trainIdx].pt for m in good_matches])
        
            return q1, q2
        else:
            return None, None

    # Function to estimate pose from two sets of corresponding image points using Essential matrix
    def get_pose(self, q1, q2):
    
        # Find Essential matrix E
        E, mask = cv2.findEssentialMat(q1, q2, self.K)

        # Decompose the Essential matrix into R and t
        R, t = self.decomp_essential_mat(E, q1, q2)

        # Get transformation matrix from R and t
        transformation_matrix = self._form_transf(R, np.squeeze(t))
        
        return transformation_matrix

    # Function to decompose Essential matrix into R and t by triangulation
    def decomp_essential_mat(self, E, q1, q2):
        def sum_z_cal_relative_scale(R, t):
            # Get the transformation matrix
            T = self._form_transf(R, t)
            # Make the projection matrix
            P = np.matmul(np.concatenate((self.K, np.zeros((3, 1))), axis=1), T)

            # Triangulate the 3D points
            hom_Q1 = cv2.triangulatePoints(self.P, P, q1.T, q2.T)
            # Also seen from cam 2
            hom_Q2 = np.matmul(T, hom_Q1)

            # Un-homogenize
            Q1 = hom_Q1[:3, :] / hom_Q1[3, :]
            Q2 = hom_Q2[:3, :] / hom_Q2[3, :]
            
            #self.world_points.append(Q1)

            # Find the number of points there has positive z coordinate in both cameras
            sum_of_pos_z_Q1 = sum(Q1[2, :] > 0)
            sum_of_pos_z_Q2 = sum(Q2[2, :] > 0)

            # Form point pairs and calculate the relative scale
            relative_scale = np.mean(np.linalg.norm(Q1.T[:-1] - Q1.T[1:], axis=-1)/
                                     np.linalg.norm(Q2.T[:-1] - Q2.T[1:], axis=-1))
            return sum_of_pos_z_Q1 + sum_of_pos_z_Q2, relative_scale

        # Decompose the essential matrix
        R1, R2, t = cv2.decomposeEssentialMat(E)
        t = np.squeeze(t)

        # Make a list of the different possible pairs
        pairs = [[R1, t], [R1, -t], [R2, t], [R2, -t]]

        # Check which solution there is the right one
        z_sums = []
        relative_scales = []
        for R, t in pairs:
            z_sum, scale = sum_z_cal_relative_scale(R, t)
            z_sums.append(z_sum)
            relative_scales.append(scale)

        # Select the pair there has the most points with positive z coordinate
        right_pair_idx = np.argmax(z_sums)
        right_pair = pairs[right_pair_idx]
        relative_scale = relative_scales[right_pair_idx]
        R1, t = right_pair
        t = t * relative_scale
        t[~np.isfinite(t)] = 0.00001
        T = self._form_transf(R1, t)
        # Make the projection matrix
        P = np.matmul(np.concatenate((self.K, np.zeros((3, 1))), axis=1), T)
        # Triangulate the 3D points
        hom_Q1 = cv2.triangulatePoints(P, P, q1.T, q2.T)
        # Also seen from cam 2
        hom_Q2 = np.matmul(T, hom_Q1)

        # Un-homogenize
        Q1 = hom_Q1[:3, :] / hom_Q1[3, :]
        Q2 = hom_Q2[:3, :] / hom_Q2[3, :]
        
        self.world_points.append(Q1)

        return [R1, t]

# Function to convert a rotation matrix to quaternion
def matrix_to_quaternion(matrix):
    rvec, _ = cv2.Rodrigues(matrix[:3, :3])
    qx = np.sin(rvec[0]/2) * np.cos(rvec[1]/2) * np.cos(rvec[2]/2) - np.cos(rvec[0]/2) * np.sin(rvec[1]/2) * np.sin(rvec[2]/2)
    qy = np.cos(rvec[0]/2) * np.sin(rvec[1]/2) * np.cos(rvec[2]/2) + np.sin(rvec[0]/2) * np.cos(rvec[1]/2) * np.sin(rvec[2]/2)
    qz = np.cos(rvec[0]/2) * np.cos(rvec[1]/2) * np.sin(rvec[2]/2) - np.sin(rvec[0]/2) * np.sin(rvec[1]/2) * np.cos(rvec[2]/2)
    qw = np.cos(rvec[0]/2) * np.cos(rvec[1]/2) * np.cos(rvec[2]/2) + np.sin(rvec[0]/2) * np.sin(rvec[1]/2) * np.sin(rvec[2]/2)
    return np.array([qx, qy, qz, qw])

# Function to undistort an image using camera_matrix and distortion coefficients
def undistort_image(image, camera_matrix, dist_coeffs):
    h, w = image.shape[:2]
    new_cam_mat, roi= cv2.getOptimalNewCameraMatrix(camera_matrix, dist_coeffs,(w,h),1,(w,h))
    undistorted_image = cv2.undistort(image,camera_matrix,dist_coeffs,None,new_cam_mat)
    return undistorted_image

# Callback function for processing images and estimating odometry
def image_callback(new_image):
    global vo_pub
    global vo
    global process_frames
    global cur_pose
    global old_frame
    global new_frame
    global bridge
    global odometry

    new_frame = bridge.imgmsg_to_cv2(new_image, "bgr8")
    #new_frame = undistort_image(new_frame, intrinsic, distortion)
    new_frame = cv2.flip(new_frame,1)

    if process_frames:
        q1, q2 = vo.get_matches(old_frame, new_frame)
        if q1 is not None:
            if (len(q1) > 20 and len(q2) > 20) and (q1.all() == q2.all()):
                transf = vo.get_pose(q1, q2)
                #cur_pose = np.dot(cur_pose,transf)  # Uncomment this line to get absolute position
                odometry.header = Header()
                odometry.header.stamp = rospy.get_rostime()
                odometry.header.frame_id = "odom"
                odometry.child_frame_id = "camera"
                odometry.pose.pose.position.x = transf[0,3]/100
                odometry.pose.pose.position.y = transf[1,3]/100
                odometry.pose.pose.position.z = transf[2,3]/100
                cur_quat = matrix_to_quaternion(cur_pose[:, 0:3])
                odometry.pose.pose.orientation.x = cur_quat[0]
                odometry.pose.pose.orientation.y = cur_quat[1]
                odometry.pose.pose.orientation.z = cur_quat[2]
                odometry.pose.pose.orientation.w = cur_quat[3]
                vo_pub.publish(odometry)
    old_frame = new_frame
    process_frames = True

# Main function
if __name__ == "__main__":
    # Read camera intrinsic and distortion parameters
    intrinsic = np.load('/home/ubuntu/Project_drone/src/visual_odometry/scripts/camera_matrix_r.npy')
    distortion = np.load('/home/ubuntu/Project_drone/src/visual_odometry/scripts/dist_coeffs_r.npy')

    # Initialize VisualOdometry object with intrinsic camera matrix
    vo = VisualOdometry(intrinsic)

    # Initialize ROS node and publisher
    rospy.init_node("visual_odometry_node")
    vo_pub = rospy.Publisher("drone/visual_odometry", Odometry, queue_size=10)

    # Subscribe to the camera topic
    image_sub = rospy.Subscriber("drone/camera/image", Image, image_callback)
    bridge = CvBridge()
    process_frames = False
    old_frame = None
    new_frame = None
    cur_pose = np.identity(4)
    odometry = Odometry()

    # Keep the node running until interrupted
    while not rospy.is_shutdown():
        rospy.spin()
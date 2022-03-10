import numpy as np
import math
import json
import copy

import trajoptpy
# generating robot trajectory
# https://rll.berkeley.edu/trajopt/doc/sphinx_build/html/

from utils.openrave_utils import *
# OPENRave = Open Robotics Automation Virtual Environment
from utils.trajectory import Trajectory

class TrajoptPlanner(object):
	"""
	This class plans a trajectory from start to goal with TrajOpt, given
	features and feature weights (optionally).
	"""
	def __init__(self, feat_list, max_iter, num_waypts, environment):

		# ---- Important internal variables ---- #
		self.feat_list = feat_list		# 'table', 'human', 'coffee', 'origin', 'laptop'
		self.num_features = len(self.feat_list)
		self.weights = [0.0] * self.num_features

		# These variables are trajopt parameters.
		self.MAX_ITER = max_iter
		self.num_waypts = num_waypts

		# Set OpenRAVE environment.
		self.environment = environment

	# ---- Costs ---- #
	
	def efficiency_cost(self, waypt):
		"""
		Computes the total efficiency cost
		---
		input waypoint, output scalar cost
		"""
		prev_waypt = waypt[0:7]
		curr_waypt = waypt[7:14]
		feature = self.environment.efficiency_features(curr_waypt,prev_waypt)
		feature_idx = self.feat_list.index('efficiency')
		return feature*self.weights[feature_idx]

	def origin_cost(self, waypt):
		"""
		Computes the total distance from EE to base of robot cost.
		---
		input waypoint, output scalar cost
		"""
		feature = self.environment.origin_features(waypt)
		feature_idx = self.feat_list.index('origin')
		return feature*self.weights[feature_idx]

	def table_cost(self, waypt):
		"""
		Computes the total distance to table cost.
		---
		input waypoint, output scalar cost
		"""
		feature = self.environment.table_features(waypt)
		feature_idx = self.feat_list.index('table')
		return feature*self.weights[feature_idx]

	def coffee_cost(self, waypt):
		"""
		Computes the total coffee (EE orientation) cost.
		---
		input waypoint, output scalar cost
		"""
		feature = self.environment.coffee_features(waypt)
		feature_idx = self.feat_list.index('coffee')
		return feature*self.weights[feature_idx]

	def laptop_cost(self, waypt):
		"""
		Computes the total distance to laptop cost
		---
		input waypoint, output scalar cost
		"""
		prev_waypt = waypt[0:7]
		curr_waypt = waypt[7:14]
		feature = self.environment.laptop_features(curr_waypt,prev_waypt)
		feature_idx = self.feat_list.index('laptop')
		return feature*self.weights[feature_idx]*np.linalg.norm(curr_waypt - prev_waypt)

	def human_cost(self, waypt):
		"""
		Computes the total distance to human cost.
		---
		input waypoint, output scalar cost
		"""
		prev_waypt = waypt[0:7]
		curr_waypt = waypt[7:14]
		feature = self.environment.human_features(curr_waypt,prev_waypt)
		feature_idx = self.feat_list.index('human')
		return feature*self.weights[feature_idx]*np.linalg.norm(curr_waypt - prev_waypt)

	# ---- Here's TrajOpt --- #

	def trajOpt(self, start, goal, goal_pose, traj_seed=None):
		"""
		Computes a plan from start to goal using trajectory optimizer.
		Reference: http://joschu.net/docs/trajopt-paper.pdf
		---
		Paramters:
			start -- The start position.
			goal -- The goal position.
			goal_pose -- The goal pose (optional: can be None).
			traj_seed [optiona] -- An optional initial trajectory seed.

		Returns:
			waypts_plan -- A downsampled trajectory resulted from the TrajOpt
			optimization problem solution.
		"""

		# --- Initialization --- #
		if len(start) < 10:
			aug_start = np.append(start.reshape(7), np.array([0,0,0]))
		self.environment.robot.SetDOFValues(aug_start)

		# --- Linear interpolation seed --- #
		if traj_seed is None:
			print("Using straight line initialization!")
			init_waypts = np.zeros((self.num_waypts,7))
			for count in range(self.num_waypts):
				init_waypts[count,:] = start + count/(self.num_waypts - 1.0)*(goal - start)
		else:
			print("Using trajectory seed initialization!")
			init_waypts = traj_seed

		# --- Request construction --- #
		# If pose is given, must include pose constraint.
		if goal_pose is not None:
			print("Using goal pose for trajopt computation.")
			xyz_target = goal_pose
			quat_target = [1,0,0,0] # wxyz
			constraint = [
				{
					"type": "pose",
					"params" : {"xyz" : xyz_target,
								"wxyz" : quat_target,
								"link": "j2s7s300_link_7",
								"rot_coeffs" : [0,0,0],
								"pos_coeffs" : [35,35,35],
								}
				}
			]
		else:
			print("Using goal for trajopt computation.")
			constraint = [
				{
					"type": "joint",
					"params": {"vals": goal.tolist()}
				}
			]

		request = {
			"basic_info": {
				"n_steps": self.num_waypts,
				"manip" : "j2s7s300",
				"start_fixed" : True,
				"max_iter" : self.MAX_ITER
			},
			"costs": [
			{
				"type": "joint_vel",
				"params": {"coeffs": [1.0]}
			}
			],
			"constraints": constraint,
			"init_info": {
				"type": "given_traj",
				"data": init_waypts.tolist()
			}
		}

		s = json.dumps(request)
		prob = trajoptpy.ConstructProblem(s, self.environment.env)

		for t in range(1,self.num_waypts):
			if 'coffee' in self.feat_list:
				prob.AddCost(self.coffee_cost, [(t,j) for j in range(7)], "coffee%i"%t)
			if 'table' in self.feat_list:
				prob.AddCost(self.table_cost, [(t,j) for j in range(7)], "table%i"%t)
			if 'laptop' in self.feat_list:
				prob.AddErrorCost(self.laptop_cost, [(t-1,j) for j in range(7)]+[(t,j) for j in range(7)], "HINGE", "laptop%i"%t)
				prob.AddCost(self.laptop_cost, [(t-1,j) for j in range(7)]+[(t,j) for j in range(7)], "laptop%i"%t)
			if 'origin' in self.feat_list:
				prob.AddCost(self.origin_cost, [(t,j) for j in range(7)], "origin%i"%t)
			if 'human' in self.feat_list:
				prob.AddCost(self.human_cost, [(t-1,j) for j in range(7)]+[(t,j) for j in range(7)], "human%i"%t)
			if 'efficiency' in self.feat_list:
				prob.AddCost(self.efficiency_cost, [(t-1,j) for j in range(7)]+[(t,j) for j in range(7)], "efficiency%i"%t)

		for t in range(1,self.num_waypts - 1):
			prob.AddConstraint(self.environment.table_constraint, [(t,j) for j in range(7)], "INEQ", "up%i"%t)

		result = trajoptpy.OptimizeProblem(prob)
		return result.GetTraj()

	def replan(self, start, goal, goal_pose, weights, T, timestep, seed=None):
		"""
		Replan the trajectory from start to goal given weights.
		---
		Parameters:
			start -- Start position
			goal -- Goal position.
			goal_pose -- Goal pose (optional: can be None).
			weights -- Weights used for the planning objective.
			T [float] -- Time horizon for the desired trajectory.
			timestep [float] -- Frequency of waypoints in desired trajectory.
		Returns:
			traj [Trajectory] -- The optimal trajectory satisfying the arguments.
		"""
		assert weights is not None, "The weights vector is empty. Cannot plan without a cost preference."
		self.weights = weights

		waypts = self.trajOpt(start, goal, goal_pose, traj_seed=seed)
		waypts_time = np.linspace(0.0, T, self.num_waypts)
		traj = Trajectory(waypts, waypts_time)
		return traj.upsample(int(T/timestep) + 1)


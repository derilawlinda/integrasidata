import numpy as np
from collections import defaultdict
from copy import copy
from itertools import combinations
from scipy.optimize import minimize
from shapely.geometry import LineString, MultiPoint, Point
from shapely.ops import nearest_points, polygonize, unary_union
from sklearn.cluster import KMeans

from .macros import get_geometries


def get_source_polygons_with_connections(target_instances, maximum_distance):
    target_geometries = get_geometries(target_instances)
    # Convert target_geometries into target_polygons using maximum_distance
    target_polygons = [x.buffer(maximum_distance) for x in target_geometries]
    # Identify overlapping areas
    sliced_polygons = get_disjoint_polygons(target_polygons)
    for polygon in sliced_polygons:
        candidates = []
        for target_instance, target_polygon in zip(
                target_instances, target_polygons):
            if target_polygon.contains(polygon.centroid):
                candidates.append(target_instance)
        polygon.candidates = candidates
    # Sort overlapping areas by overlap count
    sorted_polygons = sorted(sliced_polygons, key=lambda x: -len(x.candidates))
    # Assign target_polygons to each sorted_polygon
    target_instances = copy(target_instances)
    social_polygons, lonely_polygons = [], []
    for polygon in sorted_polygons:
        connections = []
        for target_instance in polygon.candidates:
            try:
                target_instances.remove(target_instance)
            except ValueError:
                continue
            connections.append(target_instance)
        connection_count = len(connections)
        if connection_count > 1:
            social_polygons.append(polygon)
        elif connection_count == 1:
            lonely_polygons.append(polygon)
        polygon.connections = connections
    return social_polygons + lonely_polygons


def get_disjoint_polygons(overlapping_polygons):
    'Split overlapping polygons into disjoint polygons'
    rings = [LineString(list(
        x.exterior.coords)) for x in overlapping_polygons]
    return list(polygonize(unary_union(rings)))


def get_instance_clusters(instances, cluster_count):
    geometries = get_geometries(instances)
    points = [x.centroid for x in geometries]
    xys = np.array([(point.x, point.y) for point in points])
    kmeans = KMeans(n_clusters=cluster_count).fit(xys)
    instances_by_label = defaultdict(list)
    for instance, label in zip(instances, kmeans.labels_):
        instances_by_label[label].append(instance)
    return list(instances_by_label.values())


def place_store(geometries):
    'Return the point that minimizes the sum of distances to each geometry'
    def sum_distances(xy):
        return sum(Point(xy).distance(g) for g in geometries)
    xy = geometries[0].centroid.coords[0]
    return Point(minimize(sum_distances, xy, method='L-BFGS-B').x)


def compute_angle(a_xy, b_xy, c_xy):
    # https://stackoverflow.com/a/31735642/192092
    b_xy = np.array(b_xy)
    angle1 = np.arctan2(*(a_xy - b_xy)[::-1])
    angle2 = np.arctan2(*(c_xy - b_xy)[::-1])
    angle_in_degrees = np.rad2deg(angle1 - angle2)
    if angle_in_degrees < 0:
        angle_in_degrees *= -1
    if angle_in_degrees > 180:
        angle_in_degrees = 360 - angle_in_degrees
    return angle_in_degrees


def get_line_segments(line_geometries):
    line_segments = []
    for line_geometry in line_geometries:
        line_coords = line_geometry.coords
        for segment_coords in zip(line_coords, line_coords[1:]):
            line_segments.append(LineString(segment_coords))
    return line_segments


def get_link_segments(line_geometries, link_line_maximum_length_in_meters):
    link_segments = []
    for line_geometry1, line_geometry2 in combinations(line_geometries, 2):
        distance = line_geometry1.distance(line_geometry2)
        if distance > link_line_maximum_length_in_meters:
            continue
        if distance == 0:
            continue
        link_segments.append(LineString(nearest_points(
            MultiPoint(line_geometry1.coords),
            MultiPoint(line_geometry2.coords))))
    return link_segments


def get_nearest_geometry(target_geometry, source_geometries):
    nearest_geometry = None
    nearest_distance = np.inf
    for source_geometry in source_geometries:
        distance = target_geometry.distance(source_geometry)
        if distance < nearest_distance:
            nearest_geometry = source_geometry
            nearest_distance = distance
    return nearest_geometry


def get_t_segments(point, line_segment):
    t_point_xyz = point.coords[0]

    a_point_xyz = line_segment.coords[0]
    b_point_xyz = line_segment.interpolate(
        line_segment.project(point)).coords[0]
    c_point_xyz = line_segment.coords[-1]

    return [
        LineString([t_point_xyz, b_point_xyz]),
        LineString([a_point_xyz, b_point_xyz]),
        LineString([b_point_xyz, c_point_xyz]),
    ]

import networkx as nx
import numpy as np
from collections import defaultdict
from copy import copy
from itertools import combinations
from math import ceil
from networkx.algorithms.shortest_paths import (
    shortest_path, shortest_path_length)
from os.path import join
from pandas import DataFrame
from scipy.spatial import KDTree
from shapely.geometry import LineString, Point

from .algorithms import (
    compute_angle, get_instance_clusters, get_line_segments, get_link_segments,
    get_nearest_geometry, get_source_polygons_with_connections, get_t_segments,
    place_store)
from .macros import get_geometries, get_other_endpoint_xy
from .models import Battery, PathType, Pole


def place_drop_poles(
        customers,
        drop_line_maximum_length_in_meters,
        drop_line_maximum_count_per_pole):
    drop_pole_polygons = get_source_polygons_with_connections(
        customers, drop_line_maximum_length_in_meters)
    drop_poles = []
    for polygon in drop_pole_polygons:
        pole_count = estimate_drop_pole_count(
            polygon, drop_line_maximum_count_per_pole)
        if pole_count > 1:
            clusters = get_instance_clusters(
                polygon.connections, cluster_count=pole_count)
            for customers in clusters:
                drop_poles.append(make_drop_pole(customers))
        else:
            drop_poles.append(make_drop_pole(polygon.connections))
    for index, pole in enumerate(drop_poles):
        pole.id = 'drop%s' % index
        for customer in pole._connected_customers:
            customer.pole_id = pole.id
            customer.drop_line_length_in_meters = Point(
                pole.xy).distance(customer.geometry)
    return drop_poles


def estimate_drop_pole_count(
        drop_pole_polygon, drop_line_maximum_count_per_pole):
    connection_count = len(drop_pole_polygon.connections)
    if not connection_count:
        return 1
    return ceil(connection_count / float(
        drop_line_maximum_count_per_pole))


def make_drop_pole(customers):
    pole_point = place_store(get_geometries(customers))
    pole = Pole(geometry=pole_point)
    pole._connected_customers = customers
    return pole


def place_distribution_graph_without_roads(drop_poles):
    g = nx.Graph()
    # Make paths connecting drop poles to each other
    for pole1, pole2 in combinations(drop_poles, 2):
        add_edge_from_line_segment(g, LineString([
            pole1.geometry.coords[0],
            pole2.geometry.coords[0]]), PathType.no_road)
    # Return graph
    return g


"""
def place_distribution_graph_with_roads(
        drop_poles, roads, link_line_maximum_length_in_meters):
    road_geometries = get_geometries(roads)
    road_collection = GeometryCollection(road_geometries)
    # Rank drop poles by distance to a road
    for drop_pole in drop_poles:
        drop_pole.distance_from_road_in_meters = road_collection.distance(
            drop_pole.geometry)
    sorted_drop_poles = sorted(
        drop_poles, key=lambda x: x.distance_from_road_in_meters)
    # Connect drop poles using roads
    connected_drop_poles = []
    for drop_pole in sorted_drop_poles:
        # get nearest connected drop pole
        # get nearest road
        # if nearest is drop pole, connect to that (add edge)
        # if nearest is road, connect to that (add edge)
        if not connected_drop_poles:
    # Connect road connection points using kruskals
    # Link roads
    link_segments = get_link_segments(
        road_geometries, link_line_maximum_length_in_meters)
    # Check that we have covered all road connection points
"""


def make_candidate_segment_graph(
        drop_poles, roads, link_line_maximum_length_in_meters):
    g = place_distribution_graph_without_roads(drop_poles)
    road_geometries = get_geometries(roads)
    # Make paths along link segments
    link_segments = get_link_segments(
        road_geometries, link_line_maximum_length_in_meters)
    for link_segment in link_segments:
        add_edge_from_line_segment(g, link_segment, PathType.no_road)
    # Make paths connecting drop poles to roads
    road_segments = get_line_segments(road_geometries)
    for pole in drop_poles:
        pole_point = pole.geometry
        nearest_road_segment = get_nearest_geometry(pole_point, road_segments)
        path_segment, road_segment1, road_segment2 = get_t_segments(
            pole_point, nearest_road_segment)
        road_segments.remove(nearest_road_segment)
        road_segments.extend([road_segment1, road_segment2])
        add_edge_from_line_segment(g, path_segment, PathType.no_road)
    # Make paths along road segments
    for road_segment in road_segments:
        add_edge_from_line_segment(g, road_segment, PathType.on_road)
    # Return graph
    return g


def add_edge_from_line_segment(graph, line_segment, path_type):
    point1_xyz, point2_xyz = line_segment.coords
    graph.add_edge(
        point1_xyz[:2],
        point2_xyz[:2],
        path_type=path_type,
        geometry=line_segment)


def make_candidate_segment_cost_graph(
        candidate_segment_graph, cost_per_meter_by_path_type):
    g = candidate_segment_graph
    for index, (point1_xyz, point2_xyz, d) in enumerate(g.edges(data=True)):
        path_type = d['path_type']
        cost_per_meter = cost_per_meter_by_path_type[path_type]
        d['id'] = 'candidate%s' % index
        d['cost'] = cost_per_meter * d['geometry'].length
    return g


def make_candidate_path_graph(drop_poles, candidate_segment_cost_graph):
    g = nx.Graph()
    for pole1, pole2 in combinations(drop_poles, 2):
        pole1_id = pole1.id
        pole2_id = pole2.id
        pole1_xyz = pole1.geometry.coords[0]
        pole2_xyz = pole2.geometry.coords[0]
        line_coords = shortest_path(
            candidate_segment_cost_graph, pole1_xyz, pole2_xyz, weight='cost')
        line_cost = shortest_path_length(
            candidate_segment_cost_graph, pole1_xyz, pole2_xyz, weight='cost')
        g.add_edge(
            pole1_id, pole2_id,
            id='%s-%s' % (pole1_id, pole2_id),
            path_type=None,
            geometry=LineString(line_coords),
            cost=line_cost)
    return g


def make_preferred_segment_graph(
        candidate_path_graph, candidate_segment_cost_graph):
    line_graph = nx.Graph()
    line_index = 0
    tree_graph = nx.minimum_spanning_tree(candidate_path_graph, weight='cost')
    for pole1_id, pole2_id, d in tree_graph.edges(data=True):
        line_geometry = d['geometry']
        line_segments = get_line_segments([line_geometry])
        for line_segment in line_segments:
            point1_xyz, point2_xyz = line_segment.coords
            d = candidate_segment_cost_graph[point1_xyz][point2_xyz]
            d['id'] = 'line%s' % line_index
            line_index += 1
            line_graph.add_edge(point1_xyz, point2_xyz, **d)
    return line_graph


def place_distribution_poles(
        distribution_graph,
        distribution_pole_maximum_interval_in_meters):
    distribution_poles = []
    for point1_xyz, point2_xyz, d in distribution_graph.edges(data=True):
        line_geometry = d['geometry']
        line_length_in_meters = line_geometry.length
        distribution_pole_count = int(line_length_in_meters / float(
            distribution_pole_maximum_interval_in_meters))
        segment_count = distribution_pole_count + 1
        adjusted_interval_in_meters = line_length_in_meters / float(
            segment_count)

        def make_distribution_pole(index, point):
            return Pole(id='%s-%s' % (d['id'], index), geometry=point)

        for segment_index in range(1, segment_count):
            pole = make_distribution_pole(
                segment_index, line_geometry.interpolate(
                    adjusted_interval_in_meters * segment_index))
            distribution_poles.append(pole)
    return distribution_poles


def place_batteries(drop_poles, battery_line_maximum_length_in_meters):
    battery_polygons = get_source_polygons_with_connections(
        drop_poles, battery_line_maximum_length_in_meters)
    batteries = []
    for index, battery_polygon in enumerate(battery_polygons):
        connections = battery_polygon.connections
        battery_point = place_store(get_geometries(connections))
        battery = Battery(id=index, geometry=battery_point)
        battery.drop_poles = connections
        battery.demand_in_kwh_per_day = estimate_demand_in_kwh_per_day(
            connections)
        batteries.append(battery)
    return batteries


def estimate_demand_in_kwh_per_day(drop_poles):
    demand_in_kwh_per_day = 0
    for pole in drop_poles:
        for customer in pole._connected_customers:
            demand_in_kwh_per_day += customer.demand_in_kwh_per_day
    return demand_in_kwh_per_day


def choose_lamp_poles(
        poles, customers, lamp_pole_maximum_distance_in_meters):
    remaining_customers = copy(customers)
    remaining_poles = copy(poles)
    lamp_poles = []
    while remaining_customers:
        customer_tree = KDTree([(_.x, _.y) for _ in get_geometries(
            remaining_customers)])
        pole = choose_next_pole(
            remaining_poles,
            customer_tree,
            lamp_pole_maximum_distance_in_meters)
        lamp_poles.append(pole)
        # Remove lamp pole from remaining_poles
        remaining_poles.remove(pole)
        # Remove satisfied customers from remaining_customers
        pole_point = pole.geometry
        pole_xy = pole_point.x, pole_point.y
        indices = customer_tree.query_ball_point(
            pole_xy,
            lamp_pole_maximum_distance_in_meters)
        for customer in np.array(remaining_customers)[indices]:
            remaining_customers.remove(customer)
    for pole in lamp_poles:
        pole.has_street_lamp = True
    return lamp_poles


def choose_next_pole(
        poles, customer_tree, lamp_pole_maximum_distance_in_meters):
    best_metric = np.inf, np.inf
    best_pole = None
    for pole in poles:
        metric = compute_lamp_pole_metric(
            pole, customer_tree, lamp_pole_maximum_distance_in_meters)
        if metric < best_metric:
            best_metric = metric
            best_pole = pole
    return best_pole


def compute_lamp_pole_metric(
        pole, customer_tree, lamp_pole_maximum_distance_in_meters):
    customer_count = len(customer_tree.data)
    pole_point = pole.geometry
    pole_xy = pole_point.x, pole_point.y
    distances, indices = customer_tree.query(
        pole_xy,
        k=customer_count,
        distance_upper_bound=lamp_pole_maximum_distance_in_meters)
    if not hasattr(distances, '__iter__'):
        distances = [distances]
        indices = [indices]
    distances = [x for x in distances if x < np.inf]
    indices = [x for x in indices if x != customer_count]
    return -len(indices), sum(distances)


def choose_panel_poles(
        poles, batteries, distribution_graph,
        solar_pole_minimum_count_per_kwh):
    panel_poles = []
    pole_tree = KDTree([_.xy for _ in poles])
    pole_by_xy = {_.xy: _ for _ in poles}
    for battery in batteries:
        panel_count = int(ceil(
            solar_pole_minimum_count_per_kwh * battery.demand_in_kwh_per_day))
        distance, index = pole_tree.query(battery.xy)
        battery_pole = poles[index]
        nearest_poles = get_nearest_poles_on_distribution_graph(
            battery_pole, pole_by_xy, distribution_graph)
        battery_panel_poles = []
        for pole in nearest_poles:
            if panel_count <= 0:
                break
            pole.has_panel = True
            battery_panel_poles.append(pole)
            panel_count -= 1
        battery.panel_poles = battery_panel_poles
        panel_poles.extend(battery_panel_poles)
    return panel_poles


def get_nearest_poles_on_distribution_graph(
        target_pole, pole_by_xy, distribution_graph):
    packs = []
    target_xy = target_pole.xy
    for source_xy in distribution_graph:
        path_length = shortest_path_length(
            distribution_graph, source_xy, target_xy, weight='cost')
        packs.append((path_length, source_xy))
    return [pole_by_xy[xy] for path_length, xy in sorted(
        packs) if xy in pole_by_xy]


def choose_pole_types(
        poles, distribution_graph, distribution_line_minimum_angle_in_degrees):
    for pole in poles:
        pole_xy = pole.xy
        try:
            target_xys = list(distribution_graph[pole_xy])
        except KeyError:
            print('pole at (%s, %s) is not connected' % pole_xy)
            continue
        if len(target_xys) < 2:
            pole.has_one = True
            continue
        for a_xy, c_xy in zip(target_xys, target_xys[1:]):
            angle = compute_angle(a_xy, pole_xy, c_xy)
            if angle < distribution_line_minimum_angle_in_degrees:
                pole.has_angle = True
                break
    d = defaultdict(list)
    for pole in poles:
        if pole.has_one or pole.has_angle or pole.has_panel:
            type_id = 'stumpy'
        else:
            type_id = 'gangly'
        pole.type_id = type_id
        d[type_id].append(pole)
    return dict(d)


def get_pole_angle_points(pole_lines):
    l1 = pole_lines[0].geometry
    l2 = pole_lines[1].geometry
    b_point = l1.intersection(l2)
    b_xy = b_point.x, b_point.y
    a_xy = get_other_endpoint_xy(l1, b_xy)
    c_xy = get_other_endpoint_xy(l2, b_xy)
    return a_xy, b_xy, c_xy


def save_poles(target_folder, utm_zone, poles):
    target_path = join(target_folder, 'poles.csv')
    rows = []
    for pole in poles:
        latitude, longitude = utm_zone.get_latlon(pole.xy)
        rows.append([
            pole.id,
            pole.type_id,
            len(pole._connected_customers or []),
            pole.has_panel,
            pole.has_lamp,
            pole.has_angle,
            latitude,
            longitude,
        ])
    DataFrame(rows, columns=[
        'pole_id',
        'type_id',
        'customer_count',
        'has_panel',
        'has_lamp',
        'has_angle',
        'latitude',
        'longitude',
    ]).to_csv(target_path, index=False)
    return target_path


def save_lines(target_folder, utm_zone, distribution_graph):
    target_path = join(target_folder, 'lines.csv')
    rows = []
    for point1_xyz, point2_xyz, d in distribution_graph.edges(data=True):
        line_geometry = d['geometry']
        line_coords = [utm_zone.get_latlon(_) for _ in line_geometry.coords]
        rows.append([
            d['id'],
            LineString(line_coords).wkt,
            line_geometry.length,
        ])
    DataFrame(rows, columns=[
        'id',
        'wkt'
        'length_in_meters',
    ]).to_csv(target_path, index=False)
    return target_path


def save_batteries(target_folder, utm_zone, batteries):
    target_path = join(target_folder, 'batteries.csv')
    rows = []
    for battery in batteries:
        latitude, longitude = utm_zone.get_latlon(battery.xy)
        rows.append([
            battery.id,
            battery.demand_in_kwh_per_day,
            len(battery.panel_poles),
            latitude,
            longitude,
        ])
    DataFrame(rows, columns=[
        'battery_id',
        'demand_in_kwh_per_day',
        'panel_count',
        'latitude',
        'longitude',
    ]).to_csv(target_path, index=False)
    return target_path


def save_map(target_folder, utm_zone, customers, distribution_lines):
    target_path = join(target_folder, 'map.csv')
    rows = []
    for distribution_line in distribution_lines:
        line_geometry = distribution_line.geometry
        rows.append([
            'Distribution Line %s' % distribution_line.id,
            LineString([
                utm_zone.get_latlon(line_geometry.coords[0]),
                utm_zone.get_latlon(line_geometry.coords[1])]).wkt,
        ])
    for customer in customers:
        p = customer.geometry.centroid
        customer_xy = p.x, p.y
        rows.append([
            'Customer %s' % customer.id,
            Point(utm_zone.get_latlon(customer_xy)).wkt,
        ])
    DataFrame(rows, columns=[
        'Description',
        'WKT',
    ]).to_csv(target_path, index=False)
    return target_path

import attr
import geometryIO
from aenum import IntEnum
from networkx import write_gpickle
from os.path import join
from osgeo import ogr
from pandas import DataFrame
from shapely.geometry.base import BaseGeometry

from .macros import get_geometries


@attr.s
class GeometryMixin(object):

    id = attr.ib(default=0)
    geometry = attr.ib(default=attr.Factory(BaseGeometry))
    attributes = attr.ib(default=attr.Factory(dict))

    @classmethod
    def get_columns(Class):
        return ['id'] + [
            k for k, v in Class.__dict__.items() if
            not k.startswith('_') and
            not hasattr(v, '__code__') and
            not hasattr(v, '__func__')]

    @classmethod
    def load(Class, source_path, utm_zone, defaults=None, alternates=None):
        instances = []
        if not defaults:
            defaults = {}
        if not alternates:
            alternates = {}
        geometries, field_packs, field_definitions = geometryIO.load(
            source_path, targetProj4=utm_zone.proj4)[1:]
        for index, (
            geometry, field_pack,
        ) in enumerate(zip(geometries, field_packs)):
            d = {}
            for field_value, (
                field_name, field_type,
            ) in zip(field_pack, field_definitions):
                d[field_name] = field_value
            instance = Class(
                id=d.pop('id', index),
                geometry=geometry,
                attributes=d)
            for k, v in defaults.items():
                setattr(instance, k, d.pop(k, d.pop(alternates.get(k), v)))
            instances.append(instance)
        return instances

    @classmethod
    def save(
            Class, target_folder, target_name, source_instances, utm_zone,
            alternates=None):
        target_path = join(target_folder, target_name)
        Class.save_shp(
            target_path + '.shp.zip', source_instances, utm_zone, alternates)
        return Customer.save_csv(
            target_path + '.csv', source_instances, utm_zone)

    @classmethod
    def save_csv(Class, target_path, source_instances, utm_zone):
        rows = []
        columns = Class.get_columns()
        for instance in source_instances:
            geometry = instance.geometry
            geometry_coords = [utm_zone.get_latlon(_) for _ in geometry.coords]
            values = [instance.__dict__.get(k, Class.__dict__.get(
                k)) for k in columns]
            rows.append(values + list(instance.attributes.values()) + [
                geometry.__class__(geometry_coords).wkt])
        if source_instances:
            columns += instance.attributes.keys()
        columns += ['wkt']
        table = DataFrame(rows, columns=columns)
        table.to_csv(target_path, index=False)
        return target_path

    @classmethod
    def save_shp(
            Class, target_path, source_instances, utm_zone, alternates=None):
        rows = []
        keys = Class.get_columns()
        if not alternates:
            alternates = {}
        for instance in source_instances:
            values = [instance.__dict__.get(k, Class.__dict__.get(
                k)) for k in keys]
            rows.append(values + list(instance.attributes.values()))
        columns = [alternates.get(k, k) for k in keys]
        if not source_instances:
            field_definitions = [(k, ogr.OFTString) for k in columns]
        else:
            field_definitions = []
            columns += instance.attributes.keys()
            for k, v in zip(columns, rows[0]):
                if isinstance(v, int):
                    field_type = ogr.OFTInteger
                elif isinstance(v, float):
                    field_type = ogr.OFTReal
                else:
                    field_type = ogr.OFTString
                field_definitions.append((k, field_type))
        geometryIO.save(
            targetPath=target_path,
            targetProj4=geometryIO.proj4LL,
            sourceProj4=utm_zone.proj4,
            shapelyGeometries=get_geometries(source_instances),
            fieldPacks=rows,
            fieldDefinitions=field_definitions)
        return target_path


class PointMixin(GeometryMixin):

    @property
    def xy(self):
        return self.geometry.x, self.geometry.y


class PathType(IntEnum):

    no_road = 0
    on_road = 1


class Customer(GeometryMixin):

    demand_in_kwh_per_day = 0.


class Road(GeometryMixin):
    pass


class Pole(PointMixin):

    type_id = None
    has_one = False
    has_panel = False
    has_lamp = False
    has_angle = False
    _connected_customers = None

    def __hash__(self):
        return hash(self.id)


class Line(GeometryMixin):

    has_road = False
    length_in_meters = 0.

    @classmethod
    def save_from_graph(
            Class, target_folder, target_name, distribution_graph, utm_zone):
        write_gpickle(distribution_graph, join(
            target_folder, target_name + '.pkl'))
        source_instances = []
        for point1_xyz, point2_xyz, d in distribution_graph.edges(data=True):
            line_geometry = d['geometry']
            length_in_meters = line_geometry.length
            instance = Class(id=d['id'], geometry=line_geometry)
            instance.has_road = d['path_type']
            instance.length_in_meters = length_in_meters
            source_instances.append(instance)
        return Class.save(
            target_folder, target_name, source_instances, utm_zone,
            alternates={
                'length_in_meters': 'length',
            })


class Battery(PointMixin):

    type_id = None
    demand_in_kwh_per_day = 0
    _drop_poles = None
    _panel_poles = None

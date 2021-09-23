import geometryIO
import utm
from shapely.geometry import GeometryCollection


class UTMZone(object):

    def __init__(self, zone_number, zone_letter):
        self.zone_number = zone_number
        self.zone_letter = zone_letter
        self.proj4 = get_utm_proj4(zone_number, zone_letter)

    @classmethod
    def load(Class, geotable_path):
        lonlat_geometries = geometryIO.load(
            geotable_path, targetProj4=geometryIO.proj4LL)[1]
        lonlat_point = GeometryCollection(lonlat_geometries).centroid
        longitude, latitude = lonlat_point.x, lonlat_point.y
        zone_number, zone_letter = utm.from_latlon(latitude, longitude)[-2:]
        return Class(zone_number, zone_letter)

    def get_latlon(self, xyz):
        return utm.to_latlon(
            *xyz[:2], self.zone_number, self.zone_letter) + xyz[2:]


def get_utm_proj4(zone_number, zone_letter):
    parts = []
    parts.extend([
        '+proj=utm',
        '+zone=%s' % zone_number,
    ])
    if zone_letter.upper() < 'N':
        parts.append('+south')
    parts.extend([
        '+ellps=WGS84',
        '+datum=WGS84',
        '+units=m',
        '+no_defs',
    ])
    return ' '.join(parts)


def get_geometries(instances):
    return [x.geometry for x in instances]


def get_other_endpoint_xy(line, endpoint_xy):
    endpoint_xys = list(line.coords)
    endpoint_xys.remove(endpoint_xy)
    return endpoint_xys[0]

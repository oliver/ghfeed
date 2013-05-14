#!/usr/bin/env python
#  ghfeed - A RESTful implementation of xkcd's geohash algorithm that has an Atom feed.
#    Copyright (C) 2008  Steve Pomeroy
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
from datetime import date, datetime, timedelta
import web, md5, urllib, struct, math
import sys
cachedir = './cache/'

urls = (
	'/atom/([\d.-]+),([\d.-]+)', 'geohash_atom',
	'/atom/([\d.-]+),([\d.-]+)/(\d{4,4})-(\d{2,2})-(\d{2,2})', 'geohash_atom',
	'/([\d.-]+),([\d.-]+)', 'geohash_csv',
	'/([\d.-]+),([\d.-]+)/(\d{4,4})-(\d{2,2})-(\d{2,2})', 'geohash_csv',
	'/dji', 'dji_csv',
	'/dji/(\d{4,4})-(\d{2,2})-(\d{2,2})', 'dji_csv',
	'/', 'geohash_instructions',
	'', 'geohash_instructions'
)
app = web.application(urls, globals())

render = web.template.render('templates/')

class geohash_instructions:
	def GET(self):
		web.header("Content-type", "text/plain")
		return """Simple RESTful Geohashing interface
CSV:
/LAT,LON
/LAT,LON/YYYY-MM-DD

Atom:
/atom/LAT,LON
/atom/LAT,LON/YYYY-MM-DD

where LAT and LON are latitude and longitude expressed in decimal format (only integer portions are needed).

Additionally:

/dji
/dji/YYYY-MM-DD
"""


def distance_on_unit_sphere(lat1, long1, lat2, long2):
	"""
	Calculates the distance (in kilometers) between two coordinates on the earth,
	assuming the earth is perfectly spherical.
	Taken from http://www.johndcook.com/python_longitude_latitude.html .
	"""

	# Convert latitude and longitude to
	# spherical coordinates in radians.
	degrees_to_radians = math.pi/180.0

	# phi = 90 - latitude
	phi1 = (90.0 - lat1)*degrees_to_radians
	phi2 = (90.0 - lat2)*degrees_to_radians

	# theta = longitude
	theta1 = long1*degrees_to_radians
	theta2 = long2*degrees_to_radians

	# Compute spherical distance from spherical coordinates.

	# For two locations in spherical coordinates
	# (1, theta, phi) and (1, theta, phi)
	# cosine( arc length ) =
	#    sin phi sin phi' cos(theta-theta') + cos phi cos phi'
	# distance = rho * arc length

	cos = (math.sin(phi1)*math.sin(phi2)*math.cos(theta1 - theta2) +
		   math.cos(phi1)*math.cos(phi2))
	arc = math.acos( cos )

	# Multiply arc by the radius of the earth (in km) to get length.
	EARTH_RADIUS_KM = 6373
	return arc * EARTH_RADIUS_KM


class MissingDataException(Exception):
	pass

class geohash:
	def __init__(self):
		self.dji_retriever = crox_dji()

	def gen_geohash(self, lat, lon, d):
		# for 30W compliance:
		# http://wiki.xkcd.com/geohashing/30W_Time_Zone_Rule
		START_DATE_FOR_30W = date(2008, 5, 27) # date when 30W rule became effective
		djiDate = d
		if float(lon) > -30.0 and djiDate >= START_DATE_FOR_30W:
			djiDate = djiDate - timedelta(1)
		dji = self.dji_retriever.get_opening(djiDate)
		to_hash = "%s-%s" % (d.isoformat(), dji)
		md5_text = md5.new(to_hash).hexdigest()
		lat_dec = 0.0
		lon_dec = 0.0
		for i in range(1,17):
			lat_dec += int(md5_text[16-i],16)
			lon_dec += int(md5_text[32-i],16)
			lat_dec /= 16
			lon_dec /= 16
		lat = int(float(lat))
		lon = int(float(lon))
		if lat >= 0:
			lat += lat_dec
		else:
			lat -= lat_dec
		if lon >= 0:
			lon += lon_dec
		else:
			lon -= lon_dec
		return lat, lon

class crox_dji:
	def __init__ (self):
		self.opening = dict()
	def get_opening(self, d):
		isofmt = d.isoformat()
		if not self.opening.has_key(isofmt):
			self.opening[isofmt] = self.__load_opening(d)
		return self.opening[isofmt]

	def __load_opening(self,d):
		url = "http://geo.crox.net/djia/%d/%d/%d" % (d.year, d.month, d.day)
		t_open = urllib.urlopen(url).read()

		if t_open.startswith("error"):
			# assume data is not available for selected date (temporarily or permanently)
			raise MissingDataException(t_open)

		return t_open.strip()


class geohash_atom:
	site_url = "http://staticfree.info/geohash/"
	gh = geohash()

	def GET(self, lat, lon, year=None,month=None,day=None):
		web.header("Content-type", "application/atom+xml")
		lat = float(lat)
		lon = float(lon)

		if day:
			d = date(int(year), int(month), int(day))
		else:
			utcTime = datetime.utcnow()
			userHourOffset = lon * 24.0 / 360.0 # estimate timezone offset from user-specified longitude
			userTime = utcTime + timedelta(hours=userHourOffset)
			d = userTime.date()

		updated = "%sT14:30:00Z" % d.isoformat()

		# find nearest geohash location (checking all neighboring graticules)
		minDist = None
		minCoords = None
		for dLat in (-1, 0, 1):
			for dLon in (-1, 0, 1):
				try:
					coords = self.gh.gen_geohash(lat+dLat, lon+dLon, d)
				except MissingDataException, e:
					# return empty feed if DJI value is missing:
					return render.geohash_atom(self.site_url, updated, False, "", "", "", "")
				dist = distance_on_unit_sphere(coords[0], coords[1], lat, lon)
				if minDist is None or dist < minDist:
					minDist = dist
					minCoords = coords

		coords = minCoords
		distKm = minDist

		lat_plain = int(coords[0])
		lon_plain = int(coords[1])
		entry_id = self.site_url + "atom/%s,%s/%s" % ( lat_plain, lon_plain, d.isoformat())
		title = "Nearest Geohash is in %s, %s on %s; %.2f km away" % (lat_plain, lon_plain, d.isoformat(), distKm)
		#url = "http://irc.peeron.com/xkcd/map/map.html?date=%s&amp;lat=%s&amp;long=%s&amp;zoom=9&amp;abs=-1" % ( d.isoformat(), lat_plain, lon_plain)
		url = "http://maps.google.com/maps?&amp;q=%s,%s&amp;z=14" % ( coords[0], coords[1])
		return render.geohash_atom(self.site_url, updated, True, title, entry_id, "%s,%s" % coords, url)

class dji_csv:
	dji = crox_dji()

	def GET(self, year=None, month=None, day=None):
		web.header("Content-type", "text/csv")
		if day:
			d = date(int(year), int(month), int(day))
		else:
			d = date.today()
		return self.dji.get_opening(d)

class geohash_csv:
	gh = geohash()

	def GET(self, lat, lon, year=None, month=None, day=None):
		web.header("Content-type", "text/csv")
		if day:
			d = date(int(year), int(month), int(day))
		else:
			d = date.today()
		return ",".join(map(str,self.gh.gen_geohash(lat, lon, d)))


def runfcgi_apache(func):
	web.wsgi.runfcgi(func, None)

# disable this line to run the script standalone (with built-in webserver):
web.wsgi.runwsgi = runfcgi_apache

if __name__ == "__main__":
	app.run()


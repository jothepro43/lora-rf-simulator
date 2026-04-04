"""KML/KMZ export endpoints for coverage and nodes."""

import io
import zipfile
import base64
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

from models.database import SessionLocal
from models.node import Node

router = APIRouter(prefix="/api/export", tags=["export"])


class CoverageExportRequest(BaseModel):
    tx_lat: float
    tx_lon: float
    tx_height_m: float = 10.0
    tx_power_dbm: float = 22.0
    tx_gain_dbi: float = 2.0
    cable_loss_db: float = 0.0
    rx_gain_dbi: float = 2.0
    rx_sensitivity_dbm: float = -148.0
    frequency_mhz: float = 915.0
    radius_km: float = 5.0
    resolution_m: float = 180.0
    rx_height_m: float = 1.5
    k_factor: float = 1.333
    rain_rate_mmh: float = 0.0
    min_dbm: float = -130.0
    max_dbm: float = -80.0
    colormap: str = "plasma"
    antenna_azimuth_deg: float = 0.0
    antenna_tilt_deg: float = 0.0
    antenna_h_beamwidth: float = 360.0
    antenna_v_beamwidth: float = 90.0
    antenna_front_to_back_db: float = 0.0
    site_name: str = "TX Site"


def _build_coverage_kml(
    site_name: str,
    tx_lat: float,
    tx_lon: float,
    tx_height_m: float,
    frequency_mhz: float,
    bounds: list,
    min_dbm: float,
    max_dbm: float,
) -> str:
    """Build KML XML string for coverage export."""
    kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = SubElement(kml, "Document")

    name_el = SubElement(doc, "name")
    name_el.text = f"LoRa Coverage - {site_name}"

    desc = SubElement(doc, "description")
    desc.text = f"{frequency_mhz} MHz coverage simulation ({min_dbm} to {max_dbm} dBm)"

    # TX Site placemark
    pm = SubElement(doc, "Placemark")
    pm_name = SubElement(pm, "name")
    pm_name.text = f"TX: {site_name}"
    pm_desc = SubElement(pm, "description")
    pm_desc.text = f"Height: {tx_height_m}m AGL, Freq: {frequency_mhz} MHz"
    point = SubElement(pm, "Point")
    coords = SubElement(point, "coordinates")
    coords.text = f"{tx_lon},{tx_lat},{tx_height_m}"

    # Style for TX marker
    style = SubElement(pm, "Style")
    icon_style = SubElement(style, "IconStyle")
    icon_scale = SubElement(icon_style, "scale")
    icon_scale.text = "1.2"
    icon_el = SubElement(icon_style, "Icon")
    href = SubElement(icon_el, "href")
    href.text = "http://maps.google.com/mapfiles/kml/shapes/ranger_station.png"

    # Coverage ground overlay
    go = SubElement(doc, "GroundOverlay")
    go_name = SubElement(go, "name")
    go_name.text = "Signal Coverage"
    go_color = SubElement(go, "color")
    go_color.text = "b3ffffff"  # semi-transparent white tint
    icon_ov = SubElement(go, "Icon")
    href_ov = SubElement(icon_ov, "href")
    href_ov.text = "coverage.png"
    latlonbox = SubElement(go, "LatLonBox")
    # bounds = [[lat_min, lon_min], [lat_max, lon_max]]
    north = SubElement(latlonbox, "north")
    north.text = str(bounds[1][0])
    south = SubElement(latlonbox, "south")
    south.text = str(bounds[0][0])
    east = SubElement(latlonbox, "east")
    east.text = str(bounds[1][1])
    west = SubElement(latlonbox, "west")
    west.text = str(bounds[0][1])

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += tostring(kml, encoding="unicode")
    return xml_str


def _create_kmz(kml_content: str, png_bytes: bytes) -> bytes:
    """Create a KMZ file (zip containing KML + PNG)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_content)
        zf.writestr("coverage.png", png_bytes)
    return buf.getvalue()


@router.post("/kml/coverage")
def export_coverage_kmz(req: CoverageExportRequest):
    """Export coverage as a KMZ file (KML + PNG in a zip)."""
    from services.coverage import generate_coverage

    result = generate_coverage(
        tx_lat=req.tx_lat,
        tx_lon=req.tx_lon,
        tx_height_m=req.tx_height_m,
        tx_power_dbm=req.tx_power_dbm,
        tx_gain_dbi=req.tx_gain_dbi,
        cable_loss_db=req.cable_loss_db,
        rx_gain_dbi=req.rx_gain_dbi,
        rx_sensitivity_dbm=req.rx_sensitivity_dbm,
        frequency_mhz=req.frequency_mhz,
        radius_km=req.radius_km,
        resolution_m=req.resolution_m,
        rx_height_m=req.rx_height_m,
        k_factor=req.k_factor,
        rain_rate_mmh=req.rain_rate_mmh,
        min_dbm=req.min_dbm,
        max_dbm=req.max_dbm,
        colormap=req.colormap,
        antenna_azimuth_deg=req.antenna_azimuth_deg,
        antenna_tilt_deg=req.antenna_tilt_deg,
        antenna_h_beamwidth=req.antenna_h_beamwidth,
        antenna_v_beamwidth=req.antenna_v_beamwidth,
        antenna_front_to_back_db=req.antenna_front_to_back_db,
    )

    png_bytes = base64.b64decode(result["image_base64"])
    kml_content = _build_coverage_kml(
        site_name=req.site_name,
        tx_lat=req.tx_lat,
        tx_lon=req.tx_lon,
        tx_height_m=req.tx_height_m,
        frequency_mhz=req.frequency_mhz,
        bounds=result["bounds"],
        min_dbm=req.min_dbm,
        max_dbm=req.max_dbm,
    )

    kmz_bytes = _create_kmz(kml_content, png_bytes)
    return Response(
        content=kmz_bytes,
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition": f'attachment; filename="coverage_{req.site_name}.kmz"'},
    )


@router.get("/kml/nodes")
def export_nodes_kml():
    """Export all saved nodes as KML placemarks."""
    db = SessionLocal()
    try:
        nodes = db.query(Node).all()
    finally:
        db.close()

    kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = SubElement(kml, "Document")

    name_el = SubElement(doc, "name")
    name_el.text = "LoRa Network Nodes"

    desc = SubElement(doc, "description")
    desc.text = f"{len(nodes)} Meshtastic/LoRa nodes"

    # Node style
    style = SubElement(doc, "Style", id="nodeStyle")
    icon_style = SubElement(style, "IconStyle")
    icon_scale = SubElement(icon_style, "scale")
    icon_scale.text = "1.0"
    icon_el = SubElement(icon_style, "Icon")
    href = SubElement(icon_el, "href")
    href.text = "http://maps.google.com/mapfiles/kml/shapes/ranger_station.png"

    for node in nodes:
        pm = SubElement(doc, "Placemark")
        pm_name = SubElement(pm, "name")
        pm_name.text = node.name or "Node"
        pm_desc = SubElement(pm, "description")
        pm_desc.text = (
            f"Device: {node.device_preset}\n"
            f"Antenna: {node.antenna_preset}\n"
            f"TX Power: {node.tx_power_dbm} dBm\n"
            f"Frequency: {node.frequency_mhz} MHz\n"
            f"Height: {node.height_agl}m AGL\n"
            f"Role: {node.role}"
        )
        style_url = SubElement(pm, "styleUrl")
        style_url.text = "#nodeStyle"
        point = SubElement(pm, "Point")
        coords = SubElement(point, "coordinates")
        coords.text = f"{node.lon},{node.lat},{node.height_agl}"

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_str += tostring(kml, encoding="unicode")

    return Response(
        content=xml_str,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": 'attachment; filename="nodes.kml"'},
    )

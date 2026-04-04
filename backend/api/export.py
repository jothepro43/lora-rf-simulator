"""KML/KMZ export API endpoints."""

import io
import math
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from models.database import get_db
from models.node import Node

router = APIRouter(prefix="/api/export", tags=["export"])


def _build_kml_document(name: str, description: str = "") -> ET.Element:
    """Create the root KML document element."""
    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = name
    if description:
        ET.SubElement(doc, "description").text = description
    return kml


def _add_placemark(doc: ET.Element, name: str, lon: float, lat: float,
                   alt: float = 0, description: str = "") -> None:
    """Add a Placemark with a Point to the document."""
    pm = ET.SubElement(doc, "Placemark")
    ET.SubElement(pm, "name").text = name
    if description:
        ET.SubElement(pm, "description").text = description

    # Style with radio tower icon
    style = ET.SubElement(pm, "Style")
    icon_style = ET.SubElement(style, "IconStyle")
    icon = ET.SubElement(icon_style, "Icon")
    ET.SubElement(icon, "href").text = (
        "http://maps.google.com/mapfiles/kml/shapes/ranger_station.png"
    )

    point = ET.SubElement(pm, "Point")
    ET.SubElement(point, "coordinates").text = f"{lon},{lat},{alt}"


def _add_ground_overlay(doc: ET.Element, name: str, png_filename: str,
                        north: float, south: float, east: float, west: float,
                        transparency_hex: str = "b3") -> None:
    """Add a GroundOverlay referencing a PNG file."""
    overlay = ET.SubElement(doc, "GroundOverlay")
    ET.SubElement(overlay, "name").text = name
    ET.SubElement(overlay, "color").text = f"{transparency_hex}ffffff"
    icon = ET.SubElement(overlay, "Icon")
    ET.SubElement(icon, "href").text = png_filename
    lat_lon_box = ET.SubElement(overlay, "LatLonBox")
    ET.SubElement(lat_lon_box, "north").text = str(north)
    ET.SubElement(lat_lon_box, "south").text = str(south)
    ET.SubElement(lat_lon_box, "east").text = str(east)
    ET.SubElement(lat_lon_box, "west").text = str(west)


def _kml_to_string(kml: ET.Element) -> str:
    """Serialize KML element tree to XML string."""
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        kml, encoding="unicode"
    )


def _create_kmz(kml_content: str, png_bytes: bytes = None,
                legend_bytes: bytes = None) -> bytes:
    """Bundle KML + images into a KMZ (zip) file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_content)
        if png_bytes:
            zf.writestr("coverage.png", png_bytes)
        if legend_bytes:
            zf.writestr("legend.png", legend_bytes)
    return buf.getvalue()


@router.get("/kml/coverage")
def export_coverage_kml(
    tx_lat: float = Query(...),
    tx_lon: float = Query(...),
    tx_height_m: float = Query(10.0),
    tx_power_dbm: float = Query(22.0),
    tx_gain_dbi: float = Query(2.0),
    cable_loss_db: float = Query(0.0),
    rx_gain_dbi: float = Query(2.0),
    rx_sensitivity_dbm: float = Query(-148.0),
    frequency_mhz: float = Query(915.0),
    radius_km: float = Query(5.0),
    resolution_m: float = Query(180.0),
    rx_height_m: float = Query(1.5),
    k_factor: float = Query(1.333),
    rain_rate_mmh: float = Query(0.0),
    min_dbm: float = Query(-130.0),
    max_dbm: float = Query(-80.0),
    colormap: str = Query("plasma"),
    site_name: str = Query("LoRa Site"),
    format: str = Query("kmz"),
    antenna_azimuth_deg: float = Query(0),
    antenna_tilt_deg: float = Query(0),
    antenna_h_beamwidth: float = Query(360),
    antenna_v_beamwidth: float = Query(90),
    antenna_front_to_back_db: float = Query(0),
):
    """Export coverage as KML/KMZ with ground overlay."""
    import base64
    from services.coverage import generate_coverage

    result = generate_coverage(
        tx_lat=tx_lat,
        tx_lon=tx_lon,
        tx_height_m=tx_height_m,
        tx_power_dbm=tx_power_dbm,
        tx_gain_dbi=tx_gain_dbi,
        cable_loss_db=cable_loss_db,
        rx_gain_dbi=rx_gain_dbi,
        rx_sensitivity_dbm=rx_sensitivity_dbm,
        frequency_mhz=frequency_mhz,
        radius_km=radius_km,
        resolution_m=resolution_m,
        rx_height_m=rx_height_m,
        k_factor=k_factor,
        rain_rate_mmh=rain_rate_mmh,
        min_dbm=min_dbm,
        max_dbm=max_dbm,
        colormap=colormap,
        antenna_azimuth_deg=antenna_azimuth_deg,
        antenna_tilt_deg=antenna_tilt_deg,
        antenna_h_beamwidth=antenna_h_beamwidth,
        antenna_v_beamwidth=antenna_v_beamwidth,
        antenna_front_to_back_db=antenna_front_to_back_db,
    )

    png_bytes = base64.b64decode(result["image_base64"])
    bounds = result["bounds"]
    south, west = bounds[0]
    north, east = bounds[1]

    kml = _build_kml_document(
        f"LoRa Coverage - {site_name}",
        f"{frequency_mhz} MHz coverage simulation, EIRP={result['eirp_dbm']} dBm",
    )
    doc = kml.find("Document")

    _add_placemark(
        doc, f"TX: {site_name}", tx_lon, tx_lat, tx_height_m,
        f"Power: {tx_power_dbm} dBm, Gain: {tx_gain_dbi} dBi, EIRP: {result['eirp_dbm']} dBm",
    )
    _add_ground_overlay(doc, "Signal Coverage", "coverage.png",
                        north, south, east, west)

    kml_str = _kml_to_string(kml)

    if format == "kml":
        return Response(
            content=kml_str,
            media_type="application/vnd.google-earth.kml+xml",
            headers={"Content-Disposition": f'attachment; filename="{site_name}_coverage.kml"'},
        )

    kmz_bytes = _create_kmz(kml_str, png_bytes)
    return Response(
        content=kmz_bytes,
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition": f'attachment; filename="{site_name}_coverage.kmz"'},
    )


@router.get("/kml/nodes")
def export_nodes_kml(db: Session = Depends(get_db)):
    """Export all saved nodes as KML placemarks."""
    nodes = db.query(Node).all()

    kml = _build_kml_document("LoRa Network Nodes", "All saved node locations")
    doc = kml.find("Document")

    for node in nodes:
        desc = (
            f"Device: {node.device_preset}, "
            f"TX: {node.tx_power_dbm} dBm, "
            f"Gain: {node.antenna_gain_dbi} dBi, "
            f"Height: {node.height_agl}m AGL, "
            f"Role: {node.role}"
        )
        _add_placemark(doc, node.name, node.lon, node.lat, node.height_agl, desc)

    kml_str = _kml_to_string(kml)
    return Response(
        content=kml_str,
        media_type="application/vnd.google-earth.kml+xml",
        headers={"Content-Disposition": 'attachment; filename="nodes.kml"'},
    )

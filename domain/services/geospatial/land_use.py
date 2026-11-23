"""Static land use / land cover (LULC) statistics from MapBiomas."""

from typing import List

import ee

from domain.schemas.property_stats import LULCData, LULCStats, Value
from domain.services.geospatial.mapbiomas import (
    LULC_ASSET,
    LULC_ASSET_BASE_YEAR,
    LULC_CLASSES,
    latest_asset_year,
)


def get_land_use_land_cover(
    roi: ee.Geometry, year: int, month: int = None
) -> LULCStats:
    """
    Computes area (ha) per land use and land cover class via MapBiomas
    (Collection 10, annual integration).

    Args:
        roi (ee.Geometry): Region of interest (farm polygon).
        year (int): Reference year of the mapping (band `year - 1985`).
        month (int, optional): Ignored; kept for signature compatibility.

    Returns:
        LULCStats: Observation year and list of areas per LULC class (ha).
    """
    target_year = min(year, latest_asset_year(LULC_ASSET, base_year=LULC_ASSET_BASE_YEAR))
    class_asset = ee.Image(LULC_ASSET)
    last_class = class_asset.select(target_year - LULC_ASSET_BASE_YEAR)

    area_img = ee.Image.pixelArea().divide(10000).addBands(last_class)

    stats = area_img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
        geometry=roi,
        scale=30,
        maxPixels=1e13,
    )

    groups_info = stats.get("groups").getInfo()
    lulc_class_data_list: List[LULCData] = []

    if groups_info:
        for group in groups_info:
            class_id = int(group["class"])
            class_name = LULC_CLASSES.get(class_id)
            if class_name is None:
                class_name = f"Classe {class_id}"
            area_value = round(float(group["sum"]), 2)

            lulc_class_data_list.append(
                LULCData(
                    lulc_class=class_name,
                    amount=Value(value=area_value, unity="hectares"),
                )
            )

    return LULCStats(observation_year=target_year, data=lulc_class_data_list)

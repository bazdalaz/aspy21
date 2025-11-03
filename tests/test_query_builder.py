import pytest

from aspy21.query_builder import build_snapshot_sql_query


def test_build_snapshot_sql_query_multiple_tags():
    xml = build_snapshot_sql_query(
        tags=["GXV1255.PV", "GP901.PV"],
        datasource="IP21",
        with_description=False,
    )

    assert '<SQL g="aspy21_snapshot"' in xml
    assert 't="SQLplus"' in xml
    assert 'ds="IP21"' in xml
    assert 'm="2"' in xml
    expected_query = (
        "Select name, name->ip_input_value, name->ip_input_quality from all_records "
        "where name in ('GXV1255.PV', 'GP901.PV')"
    )
    assert expected_query in xml


def test_build_snapshot_sql_query_with_description_single_tag():
    xml = build_snapshot_sql_query(
        tags="73_V101.PHASE",
        datasource="PLANT",
        with_description=True,
    )

    expected_query = (
        "Select name, name->ip_description, name->ip_input_value, name->ip_input_quality "
        "from all_records where name in ('73_V101.PHASE')"
    )
    assert expected_query in xml
    assert 'ds="PLANT"' in xml
    assert 'm="1"' in xml


def test_build_snapshot_sql_query_requires_tag():
    with pytest.raises(ValueError):
        build_snapshot_sql_query(tags=[], datasource="IP21")

import pytest

from aspy21.query_builder import SqlSnapshotQueryBuilder


def test_build_snapshot_sql_query_multiple_tags():
    builder = SqlSnapshotQueryBuilder()
    xml = builder.build(
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
    builder = SqlSnapshotQueryBuilder()
    xml = builder.build(
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
    builder = SqlSnapshotQueryBuilder()
    with pytest.raises(ValueError):
        builder.build(tags=[], datasource="IP21")


INJECTION_TAG = "T1' or name like '%"


def _cdata_sql(xml: str) -> str:
    import xml.etree.ElementTree as ET

    return ET.fromstring(xml).text or ""


def test_history_query_escapes_quotes_in_tags():
    from aspy21.models import ReaderType
    from aspy21.query_builder import SqlHistoryQueryBuilder

    builder = SqlHistoryQueryBuilder()
    single = builder.build(INJECTION_TAG, "2025-01-01", "2025-01-02", "IP21", ReaderType.RAW)
    multi = builder.build([INJECTION_TAG, "T2"], "2025-01-01", "2025-01-02", "IP21", ReaderType.RAW)

    assert "name='T1'' or name like ''%'" in _cdata_sql(single)
    assert "name in ('T1'' or name like ''%', 'T2')" in _cdata_sql(multi)


def test_snapshot_query_escapes_quotes_in_tags():
    xml = SqlSnapshotQueryBuilder().build(tags=[INJECTION_TAG], datasource="IP21")

    assert "where name in ('T1'' or name like ''%')" in _cdata_sql(xml)


def test_search_query_escapes_quotes_in_patterns():
    from aspy21.query_builder import SqlSearchQueryBuilder

    xml = SqlSearchQueryBuilder().build(
        datasource="IP21", description="x' or '1'='1", tag_pattern="T'*"
    )
    sql = _cdata_sql(xml)

    assert "d like '%x'' or ''1''=''1%'" in sql
    assert "name like 'T''%'" in sql


def test_aggregates_query_escapes_quotes():
    import xml.etree.ElementTree as ET

    from aspy21.models import ReaderType
    from aspy21.query_builder import SqlAggregatesQueryBuilder

    builder = SqlAggregatesQueryBuilder()
    xml = builder.build(
        tags=[INJECTION_TAG],
        start="2025-01-01",
        end="2025-01-02",
        datasource="IP21",
        read_type=ReaderType.AVG,
        interval=60,
    )
    sql = ET.fromstring(xml).text or ""

    assert "name = 'T1'' or name like ''%'" in sql

    # Timestamps are parsed, so an injection attempt is rejected before building SQL
    with pytest.raises(ValueError):
        builder.build(
            tags=["T1"],
            start="2025-01-01' or '1'='1",
            end="2025-01-02",
            datasource="IP21",
            read_type=ReaderType.AVG,
            interval=60,
        )


@pytest.mark.parametrize("datasource", ['IP21" x="1', "A<B&C"])
def test_datasource_is_escaped_in_xml_attribute(datasource):
    import xml.etree.ElementTree as ET

    from aspy21.models import ReaderType
    from aspy21.query_builder import SqlHistoryQueryBuilder, SqlSearchQueryBuilder

    xmls = [
        SqlSnapshotQueryBuilder().build(tags=["T1"], datasource=datasource),
        SqlHistoryQueryBuilder().build(
            "T1", "2025-01-01", "2025-01-02", datasource, ReaderType.RAW
        ),
        SqlSearchQueryBuilder().build(datasource=datasource, description="temp"),
    ]
    for xml in xmls:
        root = ET.fromstring(xml)
        assert root.get("ds") == datasource
        assert "x" not in root.attrib


def test_cdata_terminator_is_rejected():
    from aspy21.models import ReaderType
    from aspy21.query_builder import SqlHistoryQueryBuilder

    with pytest.raises(ValueError, match=r"\]\]>"):
        SqlSnapshotQueryBuilder().build(tags=["T1]]><x/>"], datasource="IP21")
    with pytest.raises(ValueError, match=r"\]\]>"):
        SqlHistoryQueryBuilder().build("T1]]>", "2025-01-01", "2025-01-02", "IP21", ReaderType.RAW)


def test_aggregates_query_converts_timestamps_to_ip21_format():
    """IP.21 rejects ISO timestamps such as 2026-10-21T13:35:59.747433."""
    from aspy21.models import ReaderType
    from aspy21.query_builder import SqlAggregatesQueryBuilder

    xml = SqlAggregatesQueryBuilder().build(
        tags=["T1"],
        start="2026-10-21T13:35:59.747433",
        end="2026-10-21 14:35:59",
        datasource="IP21",
        read_type=ReaderType.AVG,
    )

    assert "BETWEEN '21-Oct-26 13:35:59' AND '21-Oct-26 14:35:59'" in _cdata_sql(xml)


@pytest.mark.parametrize("loc", ["de_DE.UTF-8", "fr_FR.UTF-8", "pl_PL.UTF-8"])
def test_timestamp_month_names_do_not_depend_on_locale(loc):
    import locale

    from aspy21.query_builder import sql_timestamp

    try:
        old = locale.setlocale(locale.LC_TIME)
        locale.setlocale(locale.LC_TIME, loc)
    except locale.Error:
        pytest.skip(f"locale {loc} not available")
    try:
        assert sql_timestamp("2025-10-01 08:00:00") == "01-Oct-25 08:00:00"
        assert sql_timestamp("2025-05-31 23:59:59.9") == "31-May-25 23:59:59"
    finally:
        locale.setlocale(locale.LC_TIME, old)

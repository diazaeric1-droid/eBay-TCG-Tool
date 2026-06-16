"""History persistence round-trip on a temp database."""
from tcg import storage
from tcg.models import CardIdentity, Comp, GeneratedListing, PriceReport, Valuation


def _report():
    return PriceReport(
        query="2018 topps chrome ohtani",
        valuation=Valuation(estimate=300.0, low=250.0, high=350.0, n=12,
                            currency="USD", confidence="high"),
        sold_comps=[Comp(title="a", price=300.0, listing_type="sold", source="130point")],
        sources_used=["130point (sold)"],
    )


def test_save_list_get_delete(tmp_path):
    db = tmp_path / "history.db"
    imgs = tmp_path / "images"
    storage.init_db(db)
    assert storage.count_submissions(db) == 0

    sid = storage.save_submission(
        db_path=db, images_dir=imgs,
        identity=CardIdentity(player="Shohei Ohtani", year="2018", brand="Topps"),
        listing=GeneratedListing(ebay_title="2018 Topps Chrome Ohtani RC", description="d"),
        report=_report(),
        image_jpeg=b"\xff\xd8fakejpeg", thumb_jpeg=b"\xff\xd8thumb",
    )
    assert sid
    assert storage.count_submissions(db) == 1

    rows = storage.list_submissions(db)
    assert len(rows) == 1
    assert rows[0]["player"] == "Shohei Ohtani"
    assert rows[0]["estimate"] == 300.0

    rec = storage.get_submission(db, sid)
    assert rec["title"] == "2018 Topps Chrome Ohtani RC"
    assert rec["identity"]["player"] == "Shohei Ohtani"     # JSON re-hydrated
    assert rec["report"]["valuation"]["n"] == 12
    assert (imgs / f"{sid}.jpg").exists()

    assert storage.delete_submission(db, sid) is True
    assert storage.count_submissions(db) == 0
    assert not (imgs / f"{sid}.jpg").exists()                # image cleaned up


def test_export_csv(tmp_path):
    db = tmp_path / "history.db"
    storage.save_submission(
        db_path=db, images_dir=tmp_path / "i",
        identity=CardIdentity(player="P"),
        listing=GeneratedListing(ebay_title="T"),
        report=_report(),
    )
    csv_text = storage.export_csv(db)
    assert "title" in csv_text.splitlines()[0]
    assert "T" in csv_text


def test_csv_export_neutralizes_formula_injection(tmp_path):
    db = tmp_path / "history.db"
    storage.save_submission(
        db_path=db, images_dir=tmp_path / "i",
        identity=CardIdentity(player="=HYPERLINK(\"http://evil\")"),
        listing=GeneratedListing(ebay_title="=cmd|'/c calc'!A1"),
        report=_report(),
    )
    csv_text = storage.export_csv(db)
    # Formula-leading cells must be prefixed with a quote so spreadsheets don't eval them.
    assert "'=HYPERLINK" in csv_text
    assert "'=cmd" in csv_text


def test_missing_db_is_safe(tmp_path):
    db = tmp_path / "nope.db"
    assert storage.list_submissions(db) == []
    assert storage.get_submission(db, "x") is None
    assert storage.count_submissions(db) == 0

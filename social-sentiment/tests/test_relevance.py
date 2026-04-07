"""Tests for the brand relevance classifier."""

import pytest

from nlp.relevance import BrandRelevanceClassifier


@pytest.fixture(scope="module")
def clf():
    return BrandRelevanceClassifier(brand_id="yeet_casino")


class TestHardExclusions:
    def test_yeet_baby_excluded(self, clf):
        r = clf.classify("yeet baby challenge viral video lol")
        assert not r.is_relevant
        assert r.score == 0.0
        assert "yeet baby" in r.matched_exclusions

    def test_sport_yeet_excluded(self, clf):
        r = clf.classify("he yeeted the ball over the fence lmao")
        assert not r.is_relevant

    def test_meme_excluded(self, clf):
        r = clf.classify("yeet mode activated, yeet it bro")
        assert not r.is_relevant


class TestPrimaryKeywords:
    def test_primary_match_high_score(self, clf):
        r = clf.classify("Yeet Casino just launched a new welcome bonus!")
        assert r.is_relevant
        assert r.score >= 0.85
        assert "yeet casino" in r.matched_primary

    def test_yeetcasino_compound(self, clf):
        r = clf.classify("yeetcasino.com is running a promo this weekend")
        assert r.is_relevant

    def test_case_insensitive(self, clf):
        r = clf.classify("YEET CASINO has amazing slots!")
        assert r.is_relevant


class TestSecondaryWithContext:
    def test_secondary_plus_casino_relevant(self, clf):
        r = clf.classify("yeet deposit failed on the casino site")
        assert r.is_relevant
        assert r.score >= 0.4

    def test_secondary_without_context_irrelevant(self, clf):
        r = clf.classify("yeet is my favourite word ever lol")
        assert not r.is_relevant

    def test_yeet_slots_relevant(self, clf):
        r = clf.classify("yeet slots have a 96% RTP, pretty solid")
        assert r.is_relevant


class TestDerivedLabels:
    def test_scam_label_detected(self, clf):
        r = clf.classify("yeet casino is a total scam, they stole my money")
        assert "scam_concern" in r.derived_labels

    def test_payment_label_detected(self, clf):
        r = clf.classify(
            "yeet casino withdrawal pending for 3 days, can't get my funds"
        )
        assert "payment_issue" in r.derived_labels

    def test_ux_praise_label(self, clf):
        r = clf.classify("yeet casino fast payout, cashed out in 2 hours!")
        assert "ux_praise" in r.derived_labels

    def test_hype_label(self, clf):
        r = clf.classify("yeet casino big win, hit the jackpot!")
        assert "hype" in r.derived_labels


class TestBatch:
    def test_batch_returns_same_count(self, clf):
        texts = ["yeet casino scam", "yeet baby meme", "nothing related here"]
        results = clf.classify_batch(texts)
        assert len(results) == 3

    def test_batch_consistency(self, clf):
        text = "yeet casino payment issue withdrawal blocked"
        single = clf.classify(text)
        batch = clf.classify_batch([text])[0]
        assert single.is_relevant == batch.is_relevant
        assert single.score == batch.score

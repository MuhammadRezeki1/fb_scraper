import unittest

import fb_keyword_monitor as monitor
import fb_search_checkpoint as checkpoint


class DeepSearchHelperTests(unittest.TestCase):
    def test_group_home_is_valid_but_not_commentable(self):
        url = "https://www.facebook.com/groups/123456789/"
        self.assertTrue(monitor._is_valid_result_url(url))
        self.assertTrue(checkpoint._is_valid_result_url(url))
        self.assertFalse(monitor._is_commentable_url(url))

    def test_hashtag_match_requires_complete_tag(self):
        self.assertTrue(monitor._hashtag_in_item({"caption": "Aksi #Demo hari ini"}, "demo"))
        self.assertFalse(monitor._hashtag_in_item({"caption": "Tentang #demokrasi"}, "demo"))

    def test_related_hashtags_are_discovered_from_cooccurrence(self):
        posts = [
            {"caption": "#demo #jakarta #viral"},
            {"text": "#Demo dan #Jakarta"},
            {"caption": "#berita tanpa tag utama"},
        ]
        self.assertEqual(
            checkpoint._generate_related_hashtags("demo", 5, posts),
            ["jakarta", "viral"],
        )

    def test_views_do_not_count_as_full_interactions(self):
        video = {"views_count": 30_000}
        post = {"likes_count": 11_900, "comments_count": 3_000}
        self.assertGreater(monitor._engagement_score(post), monitor._engagement_score(video))
        self.assertGreater(checkpoint._engagement_score(post), checkpoint._engagement_score(video))

    def test_compact_number_parser_handles_fb_formats(self):
        self.assertEqual(monitor._parse_compact_number("48 rb Tayangan"), 48000)
        self.assertEqual(monitor._parse_compact_number("1,2 jt views"), 1200000)
        self.assertEqual(monitor._parse_compact_number("2.345 komentar"), 2345)

    def test_metric_text_parser_handles_video_dom_text(self):
        scraper = monitor.FacebookKeywordMonitor.__new__(monitor.FacebookKeywordMonitor)
        text = "Polda metro jaya buka suara. 48 rb Tayangan 1,2 rb komentar 31 kali dibagikan"
        self.assertEqual(scraper._extract_metric_from_text(text, ["tayangan", "views"]), 48000)
        self.assertEqual(scraper._extract_metric_from_text(text, ["komentar", "comments"]), 1200)
        self.assertEqual(scraper._extract_metric_from_text(text, ["dibagikan", "shares", "share", "bagikan"]), 31)

    def test_group_and_post_results_survive_checkpoint_merge(self):
        group = {"url": "https://www.facebook.com/groups/123456789/"}
        post = {"url": "https://www.facebook.com/acme/posts/987654321"}
        merged = []
        added = checkpoint._merge_posts([group, post], set(), merged, "query")
        self.assertEqual(added, 2)

    def test_multi_query_split_and_root_source_metadata(self):
        self.assertEqual(
            checkpoint._split_multi_query("bemui, bemugm\ndemo"),
            ["bemui", "bemugm", "demo"],
        )
        merged = []
        added = checkpoint._merge_posts(
            [{"url": "https://www.facebook.com/acme/posts/987654321"}],
            set(),
            merged,
            "bemui terbaru",
            "deep_source",
            "bemui",
        )
        self.assertEqual(added, 1)
        self.assertEqual(merged[0]["deep_source"], "bemui terbaru")
        self.assertEqual(merged[0]["deep_root_query"], "bemui")

    def test_watch_live_and_canonical_video_share_content_key(self):
        live = "https://www.facebook.com/watch/live/?ref=watch_permalink&v=845392464926950"
        canonical = "https://www.facebook.com/61585548254778/videos/845392464926950/"
        self.assertTrue(monitor._is_valid_result_url(live))
        self.assertTrue(checkpoint._is_valid_result_url(live))
        self.assertEqual(monitor._normalize_fb_url(live), "https://www.facebook.com/watch/?v=845392464926950")
        self.assertEqual(monitor._fb_content_key(live), monitor._fb_content_key(canonical))
        self.assertEqual(checkpoint._content_key(live), checkpoint._content_key(canonical))

    def test_checkpoint_duplicate_prefers_canonical_video_permalink(self):
        posts = []
        seen = set()
        added = checkpoint._merge_posts(
            [{"url": "https://www.facebook.com/watch/?v=845392464926950", "views_count": 1_900_000}],
            seen,
            posts,
            "bemui",
        )
        self.assertEqual(added, 1)
        added = checkpoint._merge_posts(
            [{"url": "https://www.facebook.com/61585548254778/videos/845392464926950/", "views_count": 10_000}],
            seen,
            posts,
            "bemui",
        )
        self.assertEqual(added, 0)
        self.assertEqual(posts[0]["url"], "https://www.facebook.com/61585548254778/videos/845392464926950/")
        self.assertEqual(posts[0]["views_count"], 1_900_000)

    def test_checkpoint_duplicate_keeps_highest_views(self):
        posts = []
        seen = set()
        checkpoint._merge_posts(
            [{"url": "https://www.facebook.com/KOMPAScom/videos/840505128792130/", "views_count": 306_000}],
            seen,
            posts,
            "bemui",
        )
        checkpoint._merge_posts(
            [{"url": "https://www.facebook.com/KOMPAScom/videos/840505128792130/", "views_count": 562_000}],
            seen,
            posts,
            "bemui",
        )
        self.assertEqual(posts[0]["views_count"], 562_000)


if __name__ == "__main__":
    unittest.main()

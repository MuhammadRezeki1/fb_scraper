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

    def test_group_and_post_results_survive_checkpoint_merge(self):
        group = {"url": "https://www.facebook.com/groups/123456789/"}
        post = {"url": "https://www.facebook.com/acme/posts/987654321"}
        merged = []
        added = checkpoint._merge_posts([group, post], set(), merged, "query")
        self.assertEqual(added, 2)


if __name__ == "__main__":
    unittest.main()

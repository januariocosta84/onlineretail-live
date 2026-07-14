"""Re-run sentiment analysis over all comments.

Run this after extending the lexicon in olretail/sentiment.py:
    python manage.py analyze_comments
"""

from django.core.management.base import BaseCommand

from olretail.models import Comment
from olretail.sentiment import analyze


class Command(BaseCommand):
    help = "Recompute the sentiment label and score of every comment."

    def handle(self, *args, **options):
        changed = 0
        for comment in Comment.objects.all():
            label, score = analyze(comment.body)
            if label != comment.sentiment or score != comment.sentiment_score:
                Comment.objects.filter(pk=comment.pk).update(
                    sentiment=label, sentiment_score=score
                )
                changed += 1
        total = Comment.objects.count()
        self.stdout.write(f"{total} comment(s) analyzed, {changed} updated.")

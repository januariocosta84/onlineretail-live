"""Sentiment analysis fields on comments, with backfill of existing rows."""

from django.db import migrations, models


def backfill_sentiment(apps, schema_editor):
    from olretail.sentiment import analyze

    Comment = apps.get_model("olretail", "Comment")
    for comment in Comment.objects.all():
        label, score = analyze(comment.body)
        Comment.objects.filter(pk=comment.pk).update(
            sentiment=label, sentiment_score=score
        )


class Migration(migrations.Migration):

    dependencies = [
        ("olretail", "0004_product_status_workflow"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="sentiment",
            field=models.CharField(
                choices=[
                    ("positive", "Positive"),
                    ("neutral", "Neutral"),
                    ("negative", "Negative"),
                ],
                db_index=True,
                default="neutral",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="comment",
            name="sentiment_score",
            field=models.FloatField(default=0.0),
        ),
        migrations.RunPython(backfill_sentiment, migrations.RunPython.noop),
    ]

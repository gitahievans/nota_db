# Generated by Django 5.1.2 on 2025-04-21 19:40

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0004_category_pdffile_year_pdffile_categories'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pdffile',
            name='categories',
            field=models.ManyToManyField(blank=True, related_name='pdffiles', to='files.category'),
        ),
    ]

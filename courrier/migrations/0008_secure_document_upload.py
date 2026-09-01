import courrier.models
import courrier.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courrier', '0007_alter_affectation_destinataire_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='document',
            name='fichier',
            field=models.FileField(
                upload_to=courrier.models.secure_file_upload_path,
                validators=[courrier.validators.validate_document_upload],
                verbose_name='Fichier PDF numérisé',
            ),
        ),
    ]

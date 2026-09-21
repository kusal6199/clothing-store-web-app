from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("shop", "0006_normalize_loyalty_phones")]

    operations = [
        migrations.AddField(
            model_name="order",
            name="milestone_reward_item",
            field=models.ForeignKey(
                blank=True,
                help_text="The customer's selected item for a reward earned by this paid order.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="shop.orderitem",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="reward_selected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="reward_selection_source",
            field=models.CharField(
                blank=True,
                choices=[("customer", "Customer"), ("admin_override", "Administrator override")],
                max_length=20,
            ),
        ),
    ]

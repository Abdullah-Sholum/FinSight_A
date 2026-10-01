from pathlib import Path

from django.conf import settings
from django.shortcuts import render

from .insights import build_dashboard, load_master


def dashboard(request):
    path = Path(getattr(settings, "DATASET_PATH",
                        settings.BASE_DIR.parent / "Dataset" / "master.csv"))
    if not path.exists():
        return render(request, "finance/dashboard.html",
                      {"error": f"File dataset tidak ditemukan: {path}"})

    df = load_master(path)
    context = build_dashboard(df, request.GET.get("bulan"))
    return render(request, "finance/dashboard.html", context)

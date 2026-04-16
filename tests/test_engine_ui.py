from deepzero.engine.ui import PipelineDashboard


def test_pipeline_dashboard():
    stages = [
        {"name": "s1", "type": "map", "workers": 4},
        {"name": "s2", "type": "reduce"},
    ]
    dash = PipelineDashboard(stages)
    assert dash.stage_names == ["s1", "s2"]
    assert dash.stats["s1"]["passed"] == 0

    dash.set_active_stage("s1")
    assert dash.active_stage == "s1"

    dash.update_stats("s1", passed=1, filtered=2, failed=3, pending=4)
    assert dash.stats["s1"]["passed"] == 1
    assert dash.stats["s1"]["filtered"] == 2
    assert dash.stats["s1"]["failed"] == 3
    assert dash.stats["s1"]["pending"] == 4

    # testing generated layout structure
    layout = dash._generate_layout()
    assert layout is not None

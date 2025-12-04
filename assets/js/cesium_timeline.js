(function () {
    const samples = $SAMPLES_JSON;
    const sampleTimes = Array.isArray(samples)
        ? samples.map(s => (s && Number.isFinite(s.timeMs)) ? s.timeMs : null)
        : [];

    const viewer = new Cesium.Viewer('timelineContainer', {
        animation: false,
        timeline: true,
        shouldAnimate: false,
        imageryProvider: false,
        baseLayerPicker: false,
        geocoder: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        homeButton: false,
        infoBox: false,
        selectionIndicator: false
    });

    viewer.scene.canvas.style.display = 'none';
    viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

    function julianFromMs(ms) { return Cesium.JulianDate.fromDate(new Date(ms)); }
    function clampIndex(idx) { return Math.max(0, Math.min(samples.length - 1, Number(idx) || 0)); }
    function findIndexForJulian(jd) {
        if (!sampleTimes.length) return 0;
        const currentMs = Cesium.JulianDate.toDate(jd).getTime();
        for (let i = 0; i < sampleTimes.length; i++) {
            const t = sampleTimes[i];
            if (t === null) continue;
            const next = sampleTimes[Math.min(sampleTimes.length - 1, i + 1)];
            if (currentMs <= (next ?? currentMs)) { return i; }
        }
        return sampleTimes.length - 1;
    }

    function configureClock() {
        if (!sampleTimes.length) {
            if (viewer.timeline) {
                viewer.timeline.zoomTo(viewer.clock.startTime, viewer.clock.stopTime);
            }
            return;
        }

        const firstValidTime = sampleTimes.find(t => t !== null);
        const lastValidTime = [...sampleTimes].reverse().find(t => t !== null);
        if (!Number.isFinite(firstValidTime) || !Number.isFinite(lastValidTime)) {
            return;
        }

        viewer.clock.clockRange = Cesium.ClockRange.CLAMPED;
        viewer.clock.shouldAnimate = false;
        viewer.clock.startTime = julianFromMs(firstValidTime);
        viewer.clock.stopTime = julianFromMs(lastValidTime);
        viewer.clock.currentTime = viewer.clock.startTime.clone();

        if (viewer.timeline) {
            viewer.timeline.zoomTo(viewer.clock.startTime, viewer.clock.stopTime);
        }
    }

    configureClock();

    viewer.clock.onTick.addEventListener(function(clock) {
        if (!sampleTimes.length) return;
        const idx = findIndexForJulian(clock.currentTime);
        window.parent?.postMessage({ type: 'timeline-index', index: idx }, '*');
    });

    window.setTimelineIndex = function(index) {
        if (!sampleTimes.length) return;
        const clamped = clampIndex(index);
        const t = sampleTimes[clamped];
        if (!Number.isFinite(t)) return;

        viewer.clock.shouldAnimate = false;
        viewer.clock.currentTime = julianFromMs(t);
        if (viewer.timeline) {
            viewer.timeline.zoomTo(viewer.clock.currentTime, viewer.clock.stopTime);
        }
    };

    window.__cesiumTimelineReady = true;
    window.__timelineReady = true;
})();

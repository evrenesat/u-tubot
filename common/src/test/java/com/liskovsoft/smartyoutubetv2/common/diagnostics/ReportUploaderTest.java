package com.liskovsoft.smartyoutubetv2.common.diagnostics;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class ReportUploaderTest {
    private static final String RD_TOKEN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345";

    @Test
    public void aReportCarriesNoStreamAddressOrToken() throws Exception {
        JSONObject failure = new JSONObject().put("kind", "engine_error")
                .put("error", "HTTP 403 for https://addon.example/realdebrid=" + RD_TOKEN + "/s?token=zz")
                .put("ts", 5L);
        List<String> events = Arrays.asList("11-28 12:00:00.000 film.load codec=H264", "11-28 12:00:01.000 player.error " + RD_TOKEN + " seen");

        JSONObject report = ReportUploader.assemble(new JSONObject().put("version", "1"), new JSONObject(), Collections.singletonList(failure), events,
                RD_TOKEN);

        String text = report.toString();
        assertFalse(text, text.contains(RD_TOKEN));
        assertFalse(text, text.contains("token=zz"));
        assertEquals("engine_error", report.getJSONArray("failures").getJSONObject(0).getString("kind"));
        assertEquals(2, report.getJSONArray("events").length());
    }

    @Test
    public void aTooLargeReportDropsTheOldestEventsFirst() throws Exception {
        List<String> events = new ArrayList<>();
        StringBuilder filler = new StringBuilder();

        for (int i = 0; i < 1000; i++) {
            filler.append('x');
        }

        for (int i = 0; i < 3000; i++) {
            events.add("event " + i + " " + filler);
        }

        JSONObject report = ReportUploader.assemble(new JSONObject(), new JSONObject(), Collections.emptyList(), events);

        JSONArray kept = report.getJSONArray("events");
        assertTrue(kept.length() < events.size());
        assertTrue(kept.getString(kept.length() - 1).startsWith("event 2999 "));
        assertTrue(report.toString().length() <= ReportUploader.MAX_REPORT_CHARS + 200);
    }
}

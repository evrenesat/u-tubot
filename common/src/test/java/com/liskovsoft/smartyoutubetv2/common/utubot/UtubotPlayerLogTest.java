package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.After;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotPlayerLogTest {
    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();

    @After
    public void tearDown() {
        UtubotPlayerLog.useForTesting(null);
        UtubotPlayerLog.setEnabled(true);
    }

    private static String read(File file) throws Exception {
        return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    }

    @Test
    public void theRingKeepsTheNewestEventsAndNothingIsWrittenBeforeAFlush() {
        UtubotPlayerLog log = UtubotPlayerLog.createForTesting(mFolder.getRoot(), 8, 4096, 3);
        UtubotPlayerLog.useForTesting(log);

        for (int i = 0; i < 20; i++) {
            UtubotPlayerLog.event("e", String.valueOf(i));
        }

        List<String> tail = UtubotPlayerLog.tail(100);

        assertEquals(8, tail.size());
        assertTrue(tail.get(0), tail.get(0).endsWith("e 12"));
        assertTrue(tail.get(7), tail.get(7).endsWith("e 19"));
        assertEquals(0, mFolder.getRoot().listFiles().length);
    }

    @Test
    public void aFlushWritesWhatIsNewOnceAndNoteWhatTheRingDropped() throws Exception {
        UtubotPlayerLog log = UtubotPlayerLog.createForTesting(mFolder.getRoot(), 4, 4096, 3);
        UtubotPlayerLog.useForTesting(log);

        for (int i = 0; i < 6; i++) {
            UtubotPlayerLog.event("e", String.valueOf(i));
        }

        UtubotPlayerLog.flushNow();
        UtubotPlayerLog.flushNow();

        String text = read(UtubotPlayerLog.filesForUpload().get(0));
        assertTrue(text, text.contains("dropped 2 events"));
        assertEquals(text, 1, text.split("e 5").length - 1);
        assertEquals(5, text.split("\n").length);
    }

    @Test
    public void filesAreCappedAndRotated() throws Exception {
        long maxFileBytes = 2048;
        UtubotPlayerLog log = UtubotPlayerLog.createForTesting(mFolder.getRoot(), 64, maxFileBytes, 3);
        UtubotPlayerLog.useForTesting(log);

        for (int round = 0; round < 60; round++) {
            for (int i = 0; i < 10; i++) {
                UtubotPlayerLog.event("event", "round " + round + " item " + i + " padding padding padding");
            }

            UtubotPlayerLog.flushNow();
        }

        File[] files = mFolder.getRoot().listFiles();
        assertEquals(3, files.length);

        for (File file : files) {
            assertTrue(file.getName() + " " + file.length(), file.length() <= maxFileBytes + 1024);
        }

        assertTrue(read(new File(mFolder.getRoot(), "events.log")).contains("round 59"));
    }

    @Test
    public void nothingIsRecordedWhenOffAndDetailsAreRedactedOnTheWayToTheFile() throws Exception {
        UtubotPlayerLog log = UtubotPlayerLog.createForTesting(mFolder.getRoot(), 8, 4096, 3);
        UtubotPlayerLog.useForTesting(log);
        UtubotPlayerLog.setEnabled(false);
        UtubotPlayerLog.event("off");
        assertFalse(UtubotPlayerLog.isEnabled());
        assertTrue(UtubotPlayerLog.tail(10).isEmpty());

        UtubotPlayerLog.setEnabled(true);
        UtubotPlayerLog.event("open", "https://addon.example/realdebrid=ABCDEFGHIJKLMNOPQRSTUVWXYZ012345/x?token=abc");
        UtubotPlayerLog.flushNow();

        String text = read(UtubotPlayerLog.filesForUpload().get(0));
        assertFalse(text, text.contains("ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"));
        assertFalse(text, text.contains("token=abc"));
    }

    @Test
    public void uploadedFilesAreDeletedAndNewerEventsStay() throws Exception {
        UtubotPlayerLog log = UtubotPlayerLog.createForTesting(mFolder.getRoot(), 8, 4096, 3);
        UtubotPlayerLog.useForTesting(log);
        UtubotPlayerLog.event("first");
        List<File> files = UtubotPlayerLog.filesForUpload();
        UtubotPlayerLog.deleteUploaded(files);
        UtubotPlayerLog.event("second");

        List<File> next = UtubotPlayerLog.filesForUpload();

        assertEquals(1, next.size());
        String text = read(next.get(0));
        assertTrue(text.contains("second"));
        assertFalse(text.contains("first"));
    }

    @Test
    public void anErrorKeepsItsClassAndTopFramesOnly() {
        String described = UtubotPlayerLog.describe(new IllegalStateException("boom"));

        assertTrue(described, described.startsWith("IllegalStateException: boom | "));
        assertTrue(described, described.split("\\|").length <= 7);
    }
}

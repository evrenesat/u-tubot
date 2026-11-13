package com.liskovsoft.smartyoutubetv2.common.utubot;

import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotCaptionStore.StoredTrack;
import com.liskovsoft.smartyoutubetv2.common.utubot.UtubotModels.CaptionTrack;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/**
 * The caption files the TV keeps: they survive a restart (a second store over the same folder), are never replaced or lost, and only real
 * WebVTT is stored.
 */
@RunWith(RobolectricTestRunner.class)
@Config(sdk = 28)
public class UtubotCaptionStoreTest {
    private static final String VIDEO = "Lqig_Ui9Hh0";
    private static final String OTHER_VIDEO = "jNQXAC9IVRw";
    private static final byte[] TURKISH = vtt("Alper merhaba. Merhaba yaşlı dostum.");
    private static final byte[] ENGLISH = vtt("Hello Alper.");

    @Rule
    public TemporaryFolder mFolder = new TemporaryFolder();
    private File mRoot;
    private UtubotCaptionStore mStore;

    @Before
    public void setUp() {
        mRoot = new File(mFolder.getRoot(), UtubotCaptionStore.DIRECTORY);
        mStore = new UtubotCaptionStore(mRoot);
    }

    @Test
    public void aSavedTrack_isReadBackWithItsLabelAndFile() throws IOException {
        StoredTrack saved = mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 2), TURKISH);

        assertNotNull(saved);
        List<StoredTrack> tracks = mStore.tracks(VIDEO);
        assertEquals(1, tracks.size());
        assertEquals("tr", tracks.get(0).lang);
        assertEquals("Turkish (u·tubot)", tracks.get(0).label);
        assertEquals(2, tracks.get(0).speakers);
        assertArrayEquals(TURKISH, Files.readAllBytes(tracks.get(0).file.toPath()));
        assertTrue(mStore.has(VIDEO));
        assertTrue(mStore.hasTrack(VIDEO, "tr"));
    }

    @Test
    public void tracks_surviveARestart() throws IOException {
        mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), TURKISH);
        mStore.save(VIDEO, track("en", "English (u·tubot)", 0), ENGLISH);

        UtubotCaptionStore afterRestart = new UtubotCaptionStore(mRoot);

        List<StoredTrack> tracks = afterRestart.tracks(VIDEO);
        assertEquals(2, tracks.size());
        assertEquals("en", tracks.get(0).lang);
        assertEquals("English (u·tubot)", tracks.get(0).label);
        assertEquals("tr", tracks.get(1).lang);
        assertEquals("Turkish (u·tubot)", tracks.get(1).label);
        assertArrayEquals(TURKISH, Files.readAllBytes(tracks.get(1).file.toPath()));
    }

    @Test
    public void aTrackAlreadyStored_isNotReplaced() throws IOException {
        mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), TURKISH);

        StoredTrack again = mStore.save(VIDEO, track("tr", "Another label", 0), vtt("Something else"));

        assertNotNull(again);
        assertEquals("Turkish (u·tubot)", again.label);
        assertArrayEquals(TURKISH, Files.readAllBytes(again.file.toPath()));
        assertEquals(1, mStore.tracks(VIDEO).size());
    }

    @Test
    public void anotherTrack_doesNotCostTheFirst() throws IOException {
        mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), TURKISH);
        mStore.save(VIDEO, track("en", "English (u·tubot)", 0), ENGLISH);

        assertTrue(mStore.hasTrack(VIDEO, "tr"));
        assertTrue(mStore.hasTrack(VIDEO, "en"));
    }

    @Test
    public void everyVideoHasItsOwnTracks() {
        mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), TURKISH);

        assertFalse(mStore.has(OTHER_VIDEO));
        assertTrue(mStore.tracks(OTHER_VIDEO).isEmpty());
    }

    @Test
    public void aLostIndex_costsOnlyTheLabels() throws IOException {
        mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), TURKISH);
        assertTrue(new File(new File(mRoot, VIDEO), "index.json").delete());

        List<StoredTrack> tracks = new UtubotCaptionStore(mRoot).tracks(VIDEO);

        assertEquals(1, tracks.size());
        assertEquals("tr", tracks.get(0).label);
        assertArrayEquals(TURKISH, Files.readAllBytes(tracks.get(0).file.toPath()));
    }

    @Test
    public void aDamagedIndex_costsOnlyTheLabels_andIsRepairedByTheNextSave() throws IOException {
        mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), TURKISH);
        Files.write(new File(new File(mRoot, VIDEO), "index.json").toPath(), "{not json".getBytes(StandardCharsets.UTF_8));

        assertEquals(1, new UtubotCaptionStore(mRoot).tracks(VIDEO).size());

        new UtubotCaptionStore(mRoot).save(VIDEO, track("en", "English (u·tubot)", 0), ENGLISH);

        List<StoredTrack> tracks = new UtubotCaptionStore(mRoot).tracks(VIDEO);
        assertEquals(2, tracks.size());
        assertEquals("English (u·tubot)", tracks.get(0).label);
        assertArrayEquals(TURKISH, Files.readAllBytes(tracks.get(1).file.toPath()));
    }

    @Test
    public void aFileThatWasBeingWritten_isNotOffered() throws IOException {
        mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), TURKISH);
        File dir = new File(mRoot, VIDEO);
        Files.write(new File(dir, "en.vtt.tmp").toPath(), "WEBVTT\n\n1\n00:00".getBytes(StandardCharsets.UTF_8));
        assertTrue(new File(dir, "de.vtt").createNewFile());

        List<StoredTrack> tracks = new UtubotCaptionStore(mRoot).tracks(VIDEO);

        assertEquals(1, tracks.size());
        assertEquals("tr", tracks.get(0).lang);
    }

    @Test
    public void aByteOrderMark_isAccepted() {
        byte[] withMark = ("﻿" + new String(TURKISH, StandardCharsets.UTF_8)).getBytes(StandardCharsets.UTF_8);

        assertNotNull(mStore.save(VIDEO, track("tr", "Turkish (u·tubot)", 0), withMark));
    }

    @Test
    public void whatIsNotWebVtt_isNotStored() {
        assertNull(mStore.save(VIDEO, track("tr", "x", 0), "<html>502 Bad Gateway</html>".getBytes(StandardCharsets.UTF_8)));
        assertNull(mStore.save(VIDEO, track("tr", "x", 0), new byte[0]));
        assertFalse(mStore.has(VIDEO));
    }

    @Test
    public void aFileThatIsTooLarge_isNotStored() {
        byte[] huge = new byte[UtubotCaptionStore.MAX_FILE_BYTES + 1];
        byte[] header = "WEBVTT\n".getBytes(StandardCharsets.UTF_8);
        System.arraycopy(header, 0, huge, 0, header.length);

        assertNull(mStore.save(VIDEO, track("tr", "x", 0), huge));
        assertFalse(mStore.has(VIDEO));
    }

    @Test
    public void aVideoIdOrLanguageThatIsNotAFileName_isNotStored() {
        assertNull(mStore.save("../../evil", track("tr", "x", 0), TURKISH));
        assertNull(mStore.save(VIDEO, track("../tr", "x", 0), TURKISH));
        assertNull(mStore.save(VIDEO, track(null, "x", 0), TURKISH));
        assertNull(mStore.save(null, track("tr", "x", 0), TURKISH));
        assertTrue(mStore.tracks("../../evil").isEmpty());
        assertTrue(mStore.tracks(null).isEmpty());
        assertFalse(mRoot.exists());
    }

    @Test
    public void aTrackWithoutALabel_isOfferedByItsLanguage() {
        mStore.save(VIDEO, track("tr", null, 0), TURKISH);

        assertEquals("tr", mStore.tracks(VIDEO).get(0).label);
    }

    private static CaptionTrack track(String lang, String label, int speakers) {
        CaptionTrack track = new CaptionTrack();
        track.lang = lang;
        track.label = label;
        track.url = "/v1/videos/" + VIDEO + "/captions/" + lang + ".vtt";
        track.speakers = speakers;

        return track;
    }

    private static byte[] vtt(String text) {
        return ("WEBVTT\n\n1\n00:00:00.000 --> 00:00:02.360\n" + text + "\n").getBytes(StandardCharsets.UTF_8);
    }
}

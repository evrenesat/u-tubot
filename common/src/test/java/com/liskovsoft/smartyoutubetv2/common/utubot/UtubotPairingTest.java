package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class UtubotPairingTest {
    @Test
    public void acceptsSixDigits() {
        assertTrue(UtubotPairing.isValidCode("123456"));
        assertTrue(UtubotPairing.isValidCode(" 000123 "));
    }

    @Test
    public void rejectsOthers() {
        assertFalse(UtubotPairing.isValidCode("12345"));
        assertFalse(UtubotPairing.isValidCode("1234567"));
        assertFalse(UtubotPairing.isValidCode("12a456"));
        assertFalse(UtubotPairing.isValidCode(""));
        assertFalse(UtubotPairing.isValidCode(null));
    }
}

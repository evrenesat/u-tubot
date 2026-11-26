package com.liskovsoft.smartyoutubetv2.common.utubot;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public class UtubotWebAdminTest {
    @Test
    public void appends_the_one_time_token_path() {
        assertEquals("https://utubot.example.com/web-login/wtl_abc123",
                UtubotWebAdmin.loginUrl("https://utubot.example.com", "wtl_abc123"));
    }

    @Test
    public void keeps_a_local_backend_address() {
        assertEquals("http://10.0.2.2:18790/web-login/wtl_z",
                UtubotWebAdmin.loginUrl("http://10.0.2.2:18790", "wtl_z"));
    }

    @Test
    public void drops_a_trailing_slash_before_the_path() {
        assertEquals("https://utubot.example.com/web-login/wtl_abc123",
                UtubotWebAdmin.loginUrl("https://utubot.example.com/", "wtl_abc123"));
    }
}

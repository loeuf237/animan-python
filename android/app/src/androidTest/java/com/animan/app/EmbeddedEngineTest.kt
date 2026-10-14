package com.animan.app

import android.content.Intent
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.chaquo.python.Python
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL

@RunWith(AndroidJUnit4::class)
class EmbeddedEngineTest {
    private fun request(path: String, authenticated: Boolean = true): Pair<Int, String> {
        val connection = URL(EngineHost.baseUrl + path).openConnection(Proxy.NO_PROXY) as HttpURLConnection
        try {
            connection.connectTimeout = 5000; connection.readTimeout = 20000
            if (authenticated) connection.setRequestProperty("X-Animan-Session", EngineHost.token)
            val code = connection.responseCode
            val stream = if (code < 400) connection.inputStream else connection.errorStream
            return Pair(code, stream?.bufferedReader()?.use { it.readText() } ?: "")
        } finally { connection.disconnect() }
    }
    @Test fun embeddedEngineAndNativeMedia() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val intent = Intent(context, MainActivity::class.java).putExtra("test_mode", true)
        ActivityScenario.launch<MainActivity>(intent).use { scenario ->
            val deadline = System.currentTimeMillis() + 120000
            while (!EngineHost.ready && EngineHost.error == null && System.currentTimeMillis() < deadline) Thread.sleep(250)
            assertNull(EngineHost.error)
            assertTrue("Embedded Python did not become ready", EngineHost.ready)
            var page: Pair<Int, String>? = null
            repeat(30) {
                if (page == null) try { page = request("/spa/") } catch (_: Exception) { Thread.sleep(250) }
            }
            assertEquals(200, page?.first)
            assertTrue(page!!.second.contains("id=\"app\""))
            assertEquals(401, request("/api/download/status", false).first)
            assertEquals(200, request("/api/download/status").first)
            val port = EngineHost.port
            scenario.recreate()
            assertEquals("Activity recreation started another server", port, EngineHost.port)
            val report = JSONObject(Python.getInstance().getModule("android_runtime").callAttr("native_probe").toString())
            for (key in listOf("python_engine", "ffmpeg_jni", "tls", "direct_resume", "aes128_hls", "subtitle_mux", "storage_export")) assertTrue(key, report.getBoolean(key))
            assertEquals(200, request("/api/download/status").first)
            println("ANIMAN_ANDROID_PROBE=" + report.toString())
        }
    }
}

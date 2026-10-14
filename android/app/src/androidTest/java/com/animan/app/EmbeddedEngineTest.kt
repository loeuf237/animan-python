package com.animan.app

import android.content.Intent
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.io.File
import android.graphics.Bitmap
import android.webkit.WebView
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

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
        EngineHost.start(context, true)
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
            var hydrated = false
            val uiDeadline = System.currentTimeMillis() + 60000
            while (!hydrated && System.currentTimeMillis() < uiDeadline) {
                val checked = CountDownLatch(1)
                scenario.onActivity { activity ->
                    activity.findViewById<WebView>(R.id.webView).evaluateJavascript("Boolean(document.querySelector('#app .app-shell'))") {
                        hydrated = it == "true"; checked.countDown()
                    }
                }
                assertTrue(checked.await(5, TimeUnit.SECONDS))
                if (!hydrated) Thread.sleep(500)
            }
            assertTrue("Vue did not render in the installed System WebView", hydrated)
            val port = EngineHost.port
            scenario.recreate()
            assertEquals("Activity recreation started another server", port, EngineHost.port)
            val report = JSONObject(Python.getInstance().getModule("android_runtime").callAttr("native_probe").toString())
            for (key in listOf("python_engine", "ffmpeg_jni", "tls", "direct_resume", "aes128_hls", "subtitle_mux", "storage_export", "decode_verification")) assertTrue(key, report.getBoolean(key))
            assertEquals(200, request("/api/download/status").first)
            println("ANIMAN_ANDROID_PROBE=" + report.toString())
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val image = instrumentation.uiAutomation.takeScreenshot()
            assertNotNull("Screenshot could not be captured", image)
            File(instrumentation.context.getExternalFilesDir(null), "screen.png").outputStream().use {
                image.compress(Bitmap.CompressFormat.PNG, 100, it)
            }
        }
    }
}

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
import android.net.Uri
import android.provider.MediaStore
import java.security.MessageDigest

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
            val deadline = System.currentTimeMillis() + 180000
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
            val includeMedia = InstrumentationRegistry.getArguments().getString("skip_native_media") != "true"
            val report = JSONObject(Python.getInstance().getModule("android_runtime").callAttr("native_probe", includeMedia).toString())
            report.put("vue_rendered", true)
            report.put("webview_version", WebView.getCurrentWebViewPackage()?.versionName)
            if (!includeMedia) {
                val source = File(context.filesDir, "downloads/native-storage-probe.bin")
                val bytes = ByteArray(65537) { (it % 251).toByte() }
                source.parentFile?.mkdirs(); source.writeBytes(bytes)
                assertTrue(NativeHooks.progress(1, 99, "Storage probe", "native-storage-probe", "downloading"))
                try {
                    val uri = Uri.parse(NativeHooks.exportFile(source.path, "native-storage-probe"))
                    val exported = requireNotNull(context.contentResolver.openInputStream(uri)).use { it.readBytes() }
                    assertArrayEquals(bytes, exported)
                    context.contentResolver.query(uri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use {
                        assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
                    } ?: fail("Storage export is not published")
                    report.put("storage_export", true)
                } finally { NativeHooks.progress(0, 100, "Storage probe", "native-storage-probe", "completed") }
            }
            if (includeMedia) {
            val mediaPaths = report.getJSONArray("media_paths")
            for (index in 0 until mediaPaths.length()) {
                val source = File(mediaPaths.getString(index))
                val uri = Uri.parse(NativeHooks.exportFile(source.path, "validation"))
                fun hash(input: java.io.InputStream): ByteArray = input.use {
                    val digest = MessageDigest.getInstance("SHA-256")
                    val buffer = ByteArray(65536)
                    while (true) {
                        val count = it.read(buffer)
                        if (count < 0) break
                        digest.update(buffer, 0, count)
                    }
                    digest.digest()
                }
                val shared = requireNotNull(context.contentResolver.openInputStream(uri))
                assertArrayEquals("Shared download differs from verified private media", hash(source.inputStream()), hash(shared))
                context.contentResolver.query(uri, arrayOf(MediaStore.Downloads.IS_PENDING), null, null, null)?.use {
                    assertTrue(it.moveToFirst()); assertEquals(0, it.getInt(0))
                } ?: fail("Shared download was not published")
            }
            report.put("storage_export", true)
            }
            val checkedKeys = mutableListOf("python_engine", "ffmpeg_jni", "tls", "java_aes")
            if (includeMedia) checkedKeys.addAll(listOf("direct_resume", "aes128_hls", "subtitle_mux", "storage_export", "decode_verification"))
            for (key in checkedKeys) assertTrue(key, report.getBoolean(key))
            assertEquals(200, request("/api/download/status").first)
            println("ANIMAN_ANDROID_PROBE=" + report.toString())
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val image = instrumentation.uiAutomation.takeScreenshot()
            assertNotNull("Screenshot could not be captured", image)
            val pictures = requireNotNull(context.getExternalFilesDir(null))
            File(pictures, "screen.png").outputStream().use {
                image.compress(Bitmap.CompressFormat.PNG, 100, it)
            }
        }
    }
}

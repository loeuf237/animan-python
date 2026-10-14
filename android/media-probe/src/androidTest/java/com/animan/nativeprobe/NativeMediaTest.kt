package com.animan.nativeprobe

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.animan.app.MediaBridge
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class NativeMediaTest {
    private fun run(tool: String, vararg args: String): String {
        val result = JSONObject(MediaBridge.execute(tool, JSONArray(args.toList()).toString(), 120000))
        assertFalse(result.toString(), result.getBoolean("timedOut"))
        assertEquals(result.getString("stderr"), 0, result.getInt("returncode"))
        return result.getString("stdout")
    }
    @Test fun realNativeMediaCommands() {
        val root = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir
        val source = File(root, "native fixture.mp4")
        run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=10",
            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "40", "-c:v", "mpeg4", "-c:a", "aac", source.path)
        assertTrue(source.length() > 1000)
        val subtitle = File(root, "English.srt").apply { writeText("1\n00:00:00,000 --> 00:00:01,000\nNative subtitle probe\n") }
        val muxed = File(root, "native subtitle.mkv")
        run("ffmpeg", "-v", "error", "-y", "-i", source.path, "-i", subtitle.path, "-map", "0", "-map", "1", "-c", "copy", "-metadata:s:s:0", "language=eng", muxed.path)
        val streams = JSONObject(run("ffprobe", "-v", "error", "-show_streams", "-of", "json", muxed.path)).getJSONArray("streams")
        assertTrue((0 until streams.length()).any { streams.getJSONObject(it).optString("codec_type") == "subtitle" && streams.getJSONObject(it).getJSONObject("tags").optString("language") == "eng" })
        val segment = File(root, "segment.ts")
        run("ffmpeg", "-v", "error", "-y", "-i", source.path, "-t", "2", "-c:v", "mpeg2video", "-c:a", "aac", "-f", "mpegts", segment.path)
        val hls = File(root, "hls remux.mp4")
        run("ffmpeg", "-v", "error", "-y", "-i", segment.path, "-c", "copy", "-f", "mp4", hls.path)
        for (point in listOf("1", "20", "34")) run("ffmpeg", "-v", "error", "-ss", point, "-i", muxed.path, "-t", "1", "-f", "null", "-")
        val bad = JSONObject(MediaBridge.execute("ffprobe", JSONArray(listOf("-v", "error", File(root, "missing.mp4").path)).toString(), 30000))
        assertNotEquals(0, bad.getInt("returncode"))
        assertTrue(bad.getString("stderr").isNotBlank())
        println("ANIMAN_NATIVE_MEDIA_PROBE=" + JSONObject().put("abi", android.os.Build.SUPPORTED_ABIS[0])
            .put("encode", true).put("subtitle_mux", true).put("hls_remux", true).put("decode", true).put("errors_reported", true))
    }
}

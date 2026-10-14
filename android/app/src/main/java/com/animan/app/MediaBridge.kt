package com.animan.app

import com.arthenica.ffmpegkit.FFmpegKit
import com.arthenica.ffmpegkit.FFprobeKit
import com.arthenica.ffmpegkit.Session
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object MediaBridge {
    @JvmStatic fun execute(tool: String, arguments: String, timeoutMs: Int): String {
        require(tool == "ffmpeg" || tool == "ffprobe")
        val values = JSONArray(arguments)
        val args = Array(values.length()) { values.getString(it) }
        val completed = CountDownLatch(1)
        val session: Session = if (tool == "ffprobe") {
            FFprobeKit.executeWithArgumentsAsync(args) { completed.countDown() }
        } else {
            FFmpegKit.executeWithArgumentsAsync(args) { completed.countDown() }
        }
        val timedOut = !completed.await(timeoutMs.toLong(), TimeUnit.MILLISECONDS)
        if (timedOut) {
            FFmpegKit.cancel(session.sessionId)
            completed.await(5, TimeUnit.SECONDS)
        }
        val output = session.allLogsAsString ?: ""
        return JSONObject().put("returncode", session.returnCode?.value ?: -1)
            .put("stdout", output).put("stderr", if (tool == "ffprobe" && session.returnCode?.value == 0) "" else output)
            .put("timedOut", timedOut).toString()
    }
}

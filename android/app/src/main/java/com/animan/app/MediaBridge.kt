package com.animan.app

import com.arthenica.ffmpegkit.FFmpegKit
import com.arthenica.ffmpegkit.FFprobeKit
import com.arthenica.ffmpegkit.Session
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import com.arthenica.ffmpegkit.LogCallback

object MediaBridge {
    @JvmStatic fun execute(tool: String, arguments: String, timeoutMs: Int): String {
        require(tool == "ffmpeg" || tool == "ffprobe")
        val values = JSONArray(arguments)
        val args = Array(values.length()) { values.getString(it) }
        val completed = CountDownLatch(1)
        val logBytes = AtomicInteger()
        val boundedLog = LogCallback { log ->
            if (logBytes.addAndGet(log.message.length) > MAX_DIAGNOSTICS) FFmpegKit.cancel(log.sessionId)
        }
        val session: Session = if (tool == "ffprobe") {
            FFprobeKit.executeWithArgumentsAsync(args, { completed.countDown() }, boundedLog)
        } else {
            FFmpegKit.executeWithArgumentsAsync(args, { completed.countDown() }, boundedLog, null)
        }
        val timedOut = !completed.await(timeoutMs.toLong(), TimeUnit.MILLISECONDS)
        if (timedOut) {
            FFmpegKit.cancel(session.sessionId)
            completed.await(5, TimeUnit.SECONDS)
        }
        // Avoid AbstractSession.getAllLogsAsString: it creates an unbounded
        // duplicate of every diagnostic and can exhaust the Java heap.
        val output = StringBuilder()
        for (log in session.getAllLogs(1000)) {
            val remaining = MAX_DIAGNOSTICS - output.length
            if (remaining <= 0) break
            output.append(log.message.take(remaining))
        }
        val excessiveLogs = logBytes.get() > MAX_DIAGNOSTICS
        val diagnostic = if (excessiveLogs) "FFmpeg diagnostic limit exceeded; command cancelled" else output.toString()
        return JSONObject().put("returncode", if (excessiveLogs) -1 else session.returnCode?.value ?: -1)
            .put("stdout", output.toString()).put("stderr", if (tool == "ffprobe" && session.returnCode?.value == 0 && !excessiveLogs) "" else diagnostic)
            .put("timedOut", timedOut).toString()
    }
    private const val MAX_DIAGNOSTICS = 1024 * 1024
}

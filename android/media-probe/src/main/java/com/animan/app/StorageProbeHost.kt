package com.animan.app

import android.content.Context
import android.os.Handler
import android.os.Looper

// Only the engine/notification host is replaced in this test application.
// Media, permissions and export implementations are copied from the real app.
object EngineHost {
    lateinit var context: Context
    var ready = false
    var activeCount = 0
    var progress = 0
    var label = ""
    val main = Handler(Looper.getMainLooper())
}
object DownloadService {
    fun finishIdle(context: Context) { }
    fun update(context: Context) = true
}

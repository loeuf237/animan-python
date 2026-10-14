package com.animan.app

import android.content.Intent
import android.webkit.CookieManager
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

object VerificationBridge {
    @Volatile var activity: VerificationActivity? = null
    @JvmStatic fun open(url: String, userAgent: String) {
        EngineHost.main.post {
            EngineHost.context.startActivity(Intent(EngineHost.context, VerificationActivity::class.java)
                .putExtra("url", url).putExtra("user_agent", userAgent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
    @JvmStatic fun cookies(url: String): String {
        val ready = CountDownLatch(1)
        var result = ""
        EngineHost.main.post {
            try { result = CookieManager.getInstance().getCookie(url) ?: "" }
            finally { ready.countDown() }
        }
        check(ready.await(5, TimeUnit.SECONDS)) { "CookieManager did not respond" }
        return result
    }
    @JvmStatic fun close(url: String) {
        EngineHost.main.post { activity?.let { if (it.verificationUrl == url) it.finish() } }
    }
}

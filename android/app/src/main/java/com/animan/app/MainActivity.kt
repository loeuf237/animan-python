package com.animan.app

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.webkit.*
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.animan.app.databinding.ActivityMainBinding
import kotlinx.coroutines.*
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var customView: View? = null
    private var customViewCallback: WebChromeClient.CustomViewCallback? = null
    private val PREFS_NAME = "animan_prefs"
    private val KEY_SERVER_URL = "server_url"
    private var probeJob: Job? = null
    private var scanJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupWebView()
        setupUI()

        val savedUrl = getSavedServerUrl()
        connectWithProbe(savedUrl)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        val webSettings = binding.webView.settings
        webSettings.javaScriptEnabled = true
        webSettings.domStorageEnabled = true
        webSettings.databaseEnabled = true
        webSettings.mediaPlaybackRequiresUserGesture = false
        webSettings.allowFileAccess = true
        webSettings.allowContentAccess = true
        webSettings.useWideViewPort = true
        webSettings.loadWithOverviewMode = true
        webSettings.mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        webSettings.cacheMode = WebSettings.LOAD_DEFAULT

        binding.webView.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                binding.progressBar.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                binding.progressBar.visibility = View.GONE
                binding.loadingLayout.visibility = View.GONE
                binding.errorLayout.visibility = View.GONE
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                if (request?.isForMainFrame == true) {
                    binding.progressBar.visibility = View.GONE
                    binding.loadingLayout.visibility = View.GONE
                    showErrorScreen()
                }
            }
        }

        binding.webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                binding.progressBar.progress = newProgress
                if (newProgress >= 90) {
                    binding.loadingLayout.visibility = View.GONE
                }
            }

            override fun onShowCustomView(view: View?, callback: CustomViewCallback?) {
                if (customView != null) {
                    callback?.onCustomViewHidden()
                    return
                }
                customView = view
                customViewCallback = callback
                binding.webView.visibility = View.GONE
                binding.customViewContainer.visibility = View.VISIBLE
                binding.customViewContainer.addView(view)

                requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
                window.decorView.systemUiVisibility = (
                    View.SYSTEM_UI_FLAG_FULLSCREEN
                        or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                )
            }

            override fun onHideCustomView() {
                binding.customViewContainer.removeView(customView)
                customView = null
                customViewCallback?.onCustomViewHidden()
                customViewCallback = null

                binding.customViewContainer.visibility = View.GONE
                binding.webView.visibility = View.VISIBLE
                requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
                window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_VISIBLE
            }
        }

        binding.webView.setDownloadListener { url, userAgent, contentDisposition, mimetype, _ ->
            try {
                val filename = URLUtil.guessFileName(url, contentDisposition, mimetype)
                val request = DownloadManager.Request(Uri.parse(url)).apply {
                    setMimeType(mimetype)
                    addRequestHeader("User-Agent", userAgent)
                    setDescription("Téléchargement : $filename")
                    setTitle(filename)
                    setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
                }
                val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
                dm.enqueue(request)
                Toast.makeText(
                    this@MainActivity,
                    "${getString(R.string.download_started)} : $filename",
                    Toast.LENGTH_SHORT
                ).show()
            } catch (e: Exception) {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            }
        }
    }

    private fun setupUI() {
        binding.btnCancelLoading.setOnClickListener {
            probeJob?.cancel()
            binding.loadingLayout.visibility = View.GONE
            showErrorScreen()
        }

        binding.btnConnect.setOnClickListener {
            var inputUrl = binding.editServerUrl.text.toString().trim()
            if (inputUrl.isNotEmpty()) {
                if (!inputUrl.startsWith("http://") && !inputUrl.startsWith("https://")) {
                    inputUrl = "http://$inputUrl"
                }
                saveServerUrl(inputUrl)
                connectWithProbe(inputUrl)
            }
        }

        binding.btnScanLan.setOnClickListener {
            startLanAutoDiscovery()
        }

        binding.btnConnectDiscovered.setOnClickListener {
            val foundUrl = binding.txtDiscoveredUrl.text.toString().trim()
            if (foundUrl.isNotEmpty()) {
                saveServerUrl(foundUrl)
                connectWithProbe(foundUrl)
            }
        }
    }

    private fun connectWithProbe(url: String) {
        probeJob?.cancel()
        binding.errorLayout.visibility = View.GONE
        binding.loadingLayout.visibility = View.VISIBLE
        binding.txtLoadingStatus.text = "Connexion à $url..."

        probeJob = lifecycleScope.launch {
            val isReachable = withContext(Dispatchers.IO) {
                testHttpReachability(url, timeoutMs = 2000)
            }

            if (isReachable) {
                binding.webView.loadUrl(url)
            } else {
                binding.loadingLayout.visibility = View.GONE
                showErrorScreen()
                // Launch background auto-discovery
                startLanAutoDiscovery()
            }
        }
    }

    private fun showErrorScreen() {
        binding.errorLayout.visibility = View.VISIBLE
        binding.editServerUrl.setText(getSavedServerUrl())
    }

    private fun startLanAutoDiscovery() {
        scanJob?.cancel()
        binding.scanProgressLayout.visibility = View.VISIBLE
        binding.txtScanProgress.text = "Recherche d'un serveur Animan sur le réseau Wi-Fi..."

        scanJob = lifecycleScope.launch {
            val discovered = withContext(Dispatchers.IO) {
                findAnimanServerOnLan()
            }

            binding.scanProgressLayout.visibility = View.GONE
            if (discovered != null) {
                binding.discoveredCard.visibility = View.VISIBLE
                binding.txtDiscoveredUrl.text = discovered
                binding.editServerUrl.setText(discovered)
            } else {
                binding.txtScanProgress.text = "Aucun serveur détecté automatiquement."
                binding.scanProgressLayout.visibility = View.VISIBLE
            }
        }
    }

    private suspend fun findAnimanServerOnLan(): String? = withContext(Dispatchers.IO) {
        val candidates = mutableListOf<String>()

        // 1. Waydroid host, Emulator & Loopback
        candidates.add("http://192.168.240.1:8080")
        candidates.add("http://10.0.2.2:8080")
        candidates.add("http://127.0.0.1:8080")
        candidates.add("http://localhost:8080")

        // 2. Discover local IP subnet
        val localIps = getDeviceIpAddresses()
        for (ip in localIps) {
            val parts = ip.split(".")
            if (parts.size == 4) {
                val subnet = "${parts[0]}.${parts[1]}.${parts[2]}"
                // Gateway first
                candidates.add("http://$subnet.1:8080")
                candidates.add("http://$subnet.1:8000")
                // Search around device IP
                val lastOctet = parts[3].toIntOrNull() ?: 50
                for (offset in 1..25) {
                    val target1 = lastOctet - offset
                    if (target1 in 1..254) {
                        candidates.add("http://$subnet.$target1:8080")
                    }
                    val target2 = lastOctet + offset
                    if (target2 in 1..254) {
                        candidates.add("http://$subnet.$target2:8080")
                    }
                }
            }
        }

        // Test candidates concurrently in chunks
        val uniqueCandidates = candidates.distinct()
        for (chunk in uniqueCandidates.chunked(12)) {
            val deferreds = chunk.map { url ->
                async {
                    if (testHttpReachability(url, timeoutMs = 500)) url else null
                }
            }
            val results = deferreds.awaitAll()
            val found = results.firstOrNull { it != null }
            if (found != null) {
                return@withContext found
            }
        }
        null
    }

    private fun testHttpReachability(baseUrl: String, timeoutMs: Int): Boolean {
        return try {
            val testUrl = if (baseUrl.endsWith("/")) "${baseUrl}manifest.json" else "$baseUrl/manifest.json"
            val conn = URL(testUrl).openConnection() as HttpURLConnection
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.requestMethod = "GET"
            conn.instanceFollowRedirects = true
            val code = conn.responseCode
            code in 200..399
        } catch (e: Exception) {
            false
        }
    }

    private fun getDeviceIpAddresses(): List<String> {
        val ips = mutableListOf<String>()
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            while (interfaces.hasMoreElements()) {
                val iface = interfaces.nextElement()
                if (iface.isLoopback || !iface.isUp) continue
                val addresses = iface.inetAddresses
                while (addresses.hasMoreElements()) {
                    val addr = addresses.nextElement()
                    if (addr is Inet4Address && !addr.isLoopbackAddress) {
                        ips.add(addr.hostAddress ?: "")
                    }
                }
            }
        } catch (e: Exception) {
            // ignore
        }
        return ips
    }

    private fun getSavedServerUrl(): String {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_SERVER_URL, "http://localhost:8080") ?: "http://localhost:8080"
    }

    private fun saveServerUrl(url: String) {
        val prefs = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_SERVER_URL, url).apply()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (customView != null) {
            binding.webView.webChromeClient?.onHideCustomView()
        } else if (binding.errorLayout.visibility == View.VISIBLE && binding.webView.url != null) {
            binding.errorLayout.visibility = View.GONE
        } else if (binding.webView.canGoBack()) {
            binding.webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}

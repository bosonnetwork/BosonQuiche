/*
 * Copyright (c) 2026 bosonnetwork.io
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

package io.bosonnetwork.quiche.consumer;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.TextView;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/** Runs the packaged JNI checks inside a minified Android application. */
public final class ConsumerActivity extends Activity {
    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView status = new TextView(this);
        setContentView(status);
        new Thread(() -> {
            String result;
            try {
                Path certificates = getCacheDir().toPath();
                for (String name : new String[]{"server-cert.pem", "server-key.pem"}) {
                    try (InputStream input = getAssets().open(name)) {
                        Files.copy(input, certificates.resolve(name), StandardCopyOption.REPLACE_EXISTING);
                    }
                }

                ConsumerProbe.run(certificates);
                result = "BosonQuiche packaged consumer PASS";
                Log.i("BosonQuicheConsumer", result);
            } catch (Throwable error) {
                result = "BosonQuiche packaged consumer FAIL: " + error;
                Log.e("BosonQuicheConsumer", result, error);
            }

            String text = result;
            runOnUiThread(() -> status.setText(text));
        }, "quiche-consumer-probe").start();
    }
}

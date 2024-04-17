package com.example.scanner;

import android.annotation.SuppressLint;
import android.content.DialogInterface;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.text.InputType;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.TextView;
import android.widget.Toast;
import androidx.activity.result.ActivityResultLauncher;
import androidx.appcompat.app.AlertDialog;
import androidx.fragment.app.Fragment;
import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;
import java.time.Instant;
import okhttp3.OkHttpClient;
import okhttp3.ResponseBody;
import okhttp3.logging.HttpLoggingInterceptor;
import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

public class ScannerFragment extends Fragment {

    private ActivityResultLauncher<ScanOptions> barcodeLauncher;
    private TextView statusTextView;
    View container;
    ImageButton btnChangeServer;
    private Retrofit retrofit;
    private boolean isRequestInProgress = false;

    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container,
                             Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_scanner, container, false);

        statusTextView = view.findViewById(R.id.statusTextView);
        this.container = view.findViewById(R.id.scanner_container);
        ImageButton btnChangeServer = view.findViewById(R.id.btnChangeServer);
        btnChangeServer.setOnClickListener(v -> showChangeServerDialog());

        barcodeLauncher = registerForActivityResult(new ScanContract(), result -> {
            if (result.getContents() == null) {
                Toast.makeText(requireContext(), "Сканирование отменено", Toast.LENGTH_SHORT).show();
                isRequestInProgress = false;
                scanQRCode();
            } else {
                if (!isRequestInProgress) {
                    isRequestInProgress = true;
                    processQRCode(result.getContents());
                }
            }
        });

        return view;
    }


    private void updateServerAddress(String newServerAddress) {
        HttpLoggingInterceptor logging = new HttpLoggingInterceptor(message -> Log.d("HTTP", message));
        logging.setLevel(HttpLoggingInterceptor.Level.BODY);

        OkHttpClient.Builder httpClient = new OkHttpClient.Builder();
        httpClient.addInterceptor(logging);

        retrofit = new Retrofit.Builder()
                .baseUrl(newServerAddress)
                .addConverterFactory(GsonConverterFactory.create())
                .client(httpClient.build())
                .build();
    }

    private void showChangeServerDialog() {
        AlertDialog.Builder builder = new AlertDialog.Builder(requireContext());
        builder.setTitle("Изменить адрес сервера");

        final EditText input = new EditText(requireContext());
        input.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        builder.setView(input);

        builder.setPositiveButton("OK", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                String newServerAddress = input.getText().toString();
                updateServerAddress(newServerAddress);
            }
        });

        builder.setNegativeButton("Отмена", new DialogInterface.OnClickListener() {
            @Override
            public void onClick(DialogInterface dialog, int which) {
                dialog.cancel();
            }
        });

        builder.show();
    }


    private void processQRCode(String scannedData) {
        String[] values = scannedData.split(",");

        if (values.length == 3) {
            int student_id = Integer.parseInt(values[0].split(":")[1].trim());
            int subject_id = Integer.parseInt(values[1].split(":")[1].trim());
            String timestamp = values[2].split(":")[1].trim();
            Instant currentTime = Instant.now();
            long sixSecondsAgo = currentTime.minusSeconds(8).toEpochMilli();

            double epochTime = Double.parseDouble(timestamp);
            long seconds = (long) epochTime;
            long nanoAdjustment = (long) ((epochTime - seconds) * 1_000_000_000L);
            Instant qrCodeTime = Instant.ofEpochSecond(seconds, nanoAdjustment);

            if (qrCodeTime.toEpochMilli() >= sixSecondsAgo) {
                QRCodeEntry entry = new QRCodeEntry(student_id, subject_id, timestamp);
                ApiService apiService = retrofit.create(ApiService.class);

                Call<ResponseBody> call = apiService.insertQRCodeEntry(entry);

                call.enqueue(new Callback<ResponseBody>() {
                    @Override
                    public void onResponse(Call<ResponseBody> call, Response<ResponseBody> response) {
                        requireActivity().runOnUiThread(() -> {
                            if (response.isSuccessful()) {
                                container.setBackgroundColor(Color.GREEN);
                                statusTextView.setText("GOOD");
                            } else {
                                container.setBackgroundColor(Color.RED);
                                statusTextView.setText("BAD");
                            }
                            statusTextView.setVisibility(View.VISIBLE);
                            isRequestInProgress = false;

                            new Handler().postDelayed(() -> scanQRCode(), 1000);
                        });
                    }

                    @Override
                    public void onFailure(Call<ResponseBody> call, Throwable t) {
                        requireActivity().runOnUiThread(() -> {
                            container.setBackgroundColor(Color.RED);
                            statusTextView.setText("FAIL");
                            statusTextView.setVisibility(View.VISIBLE);
                            isRequestInProgress = false;

                            new Handler().postDelayed(() -> scanQRCode(), 1000);
                        });
                    }
                });
            } else {
                container.setBackgroundColor(Color.RED);
                statusTextView.setText("EXPIRED");
                statusTextView.setVisibility(View.VISIBLE);
                isRequestInProgress = false;

                new Handler().postDelayed(this::scanQRCode, 1000);
            }
        } else {
            container.setBackgroundColor(Color.RED);
            statusTextView.setVisibility(View.VISIBLE);
            statusTextView.setText("BAD");
            isRequestInProgress = false;

            new Handler().postDelayed(this::scanQRCode, 1000);
        }
    }

    public void scanQRCode() {
        requireActivity().runOnUiThread(() -> {
            statusTextView.setVisibility(View.GONE);
            container.setBackgroundColor(Color.TRANSPARENT);
        });

        ScanOptions options = new ScanOptions();
        options.setDesiredBarcodeFormats(ScanOptions.QR_CODE);
        options.setPrompt("");
        options.setCameraId(1);
        options.setBeepEnabled(true);
        options.setBarcodeImageEnabled(true);

        barcodeLauncher.launch(options);
    }

}

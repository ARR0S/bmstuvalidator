package com.example.scanner;

import android.os.Bundle;
import androidx.appcompat.app.AppCompatActivity;


public class CaptureActivityPortrait extends AppCompatActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_capture_portrait);

        getSupportFragmentManager().beginTransaction()
                .replace(R.id.main_container, new ScannerFragment())
                .commit();
    }

}
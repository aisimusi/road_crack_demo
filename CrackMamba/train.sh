cd /home/HDD3/gty/road-crack-demo/CrackMamba

EPOCHS=50  BATCH_SIZE=4 bash scripts/train_eval_uav_image_1epoch.sh

EPOCHS=50 BATCH_SIZE=4 bash scripts/train_eval_earthquake_crack_1epoch.sh

EPOCHS=500 BATCH_SIZE=2 bash scripts/train_eval_uav_image_1epoch.sh
EPOCHS=500 BATCH_SIZE=2 bash scripts/train_eval_earthquake_crack_1epoch.sh

conda run -n crackmamba python /home/HDD3/gty/road-crack-demo/scripts/train_uapd_crack_classifier.py \
  --dataset-root /home/HDD3/gty/datasets/UAPD_final \
  --work-dir /home/HDD3/gty/road-crack-demo/models/uapd_classifier


/home/ubuntu/anaconda3/envs/crackmamba/bin/python /home/HDD3/gty/road-crack-demo/scripts/train_uapd_crack_classifier.py \
  --dataset-root /home/HDD3/gty/datasets/UAPD_final \
  --work-dir /home/HDD3/gty/road-crack-demo/models/uapd_classifier_v2s \
  --model-name efficientnet_v2_s \
  --selection-metric macro_accuracy \
  --image-size 256 \
  --batch-size 16 \
  --epochs 24 \
  --lr 1.5e-4

python scripts/annotate_lane_width.py \
  --video "dji_videos/DJI_20260608151158_0002_Z.MP4" \
  --srt "dji_videos/DJI_20260608151158_0002_Z.SRT" \
  --output calibration/lane_width_samples.json \
  --csv-output calibration/lane_width_samples.csv \
  --lane-width-m 3.75 \
  --step-sec 5